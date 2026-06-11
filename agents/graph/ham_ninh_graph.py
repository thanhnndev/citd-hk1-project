"""Single LangGraph runtime for the Ham Ninh assistant."""

import asyncio
import inspect
import json
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from agents.graph.nodes import (
    NodeServices,
    configure_services,
    conversational_node,
    input_guardrails_node,
    intent_router_node,
    maps_agent_node,
    output_guardrails_node,
    rag_agent_node,
)
from agents.graph.state import (
    AgentState,
    NODE_TIMEOUT_GUARDRAILS,
    NODE_TIMEOUT_LLM,
    NODE_TIMEOUT_ROUTER,
    NODE_TIMEOUT_TOOL,
)
from langgraph.errors import NodeError, NodeTimeoutError
from agents.graph.tracing import trace_graph_turn

logger = structlog.get_logger(__name__)


TIMEOUTS = {
    "input_guardrails": NODE_TIMEOUT_GUARDRAILS,
    "intent_router": NODE_TIMEOUT_ROUTER,
    "conversational": NODE_TIMEOUT_LLM,
    "knowledge": NODE_TIMEOUT_LLM,
    "places": NODE_TIMEOUT_TOOL,
    "output_guardrails": NODE_TIMEOUT_GUARDRAILS,
}


def output_guardrails_error_handler(state: AgentState, error: NodeError) -> dict[str, Any]:
    """Gracefully degrade output grounding verification when it times out."""
    if isinstance(error.error, NodeTimeoutError):
        logger.warning(
            "graph.node_soft_timeout",
            node=error.node,
            timeout_seconds=error.error.run_timeout,
            session_id=state.get("session_id", ""),
        )
        flags = dict(state.get("guardrail_flags") or {})
        flags["output_grounding"] = {
            "verdict": "degraded",
            "reason": "timeout",
            "severity": "medium",
            "details": f"Node '{error.node}' timed out after {error.error.run_timeout}s",
        }
        update: dict[str, Any] = {"guardrail_flags": flags}
        response_text = state.get("response_text", "")
        if response_text:
            update["messages"] = [{"role": "assistant", "content": response_text}]
        return update
    raise error.error


@dataclass
class GraphResult:
    response_text: str = ""
    suggestions: list[str] = field(default_factory=list)
    citations: list[Any] = field(default_factory=list)
    places: list[Any] = field(default_factory=list)
    intent: str | None = None
    guardrail_flags: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False
    interrupted: bool = False
    interrupt: dict[str, Any] | None = None
    reasoning_log: str | None = None
    langfuse_trace_id: str | None = None


class HamNinhGraph:
    """Compile and execute the only agent workflow used by the application."""

    def __init__(
        self,
        checkpointer: Any = None,
        services: NodeServices | None = None,
        langfuse_client: Any | None = None,
    ) -> None:
        if services is not None:
            configure_services(services)
        self._checkpointer = checkpointer or InMemorySaver()
        self._langfuse_client = langfuse_client
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(AgentState)
        builder.add_node(
            "input_guardrails",
            input_guardrails_node,
            timeout=NODE_TIMEOUT_GUARDRAILS,
        )
        builder.add_node(
            "intent_router",
            intent_router_node,
            timeout=NODE_TIMEOUT_ROUTER,
        )
        builder.add_node(
            "conversational",
            conversational_node,
            timeout=NODE_TIMEOUT_LLM,
        )
        builder.add_node(
            "knowledge",
            rag_agent_node,
            timeout=NODE_TIMEOUT_LLM,
        )
        builder.add_node(
            "places",
            maps_agent_node,
            timeout=NODE_TIMEOUT_TOOL,
        )
        builder.add_node(
            "output_guardrails",
            output_guardrails_node,
            timeout=NODE_TIMEOUT_GUARDRAILS,
            error_handler=output_guardrails_error_handler,
        )

        builder.add_edge(START, "input_guardrails")
        builder.add_conditional_edges(
            "input_guardrails",
            self._after_input_guardrails,
            {"route": "intent_router", "finish": "output_guardrails"},
        )
        builder.add_conditional_edges(
            "intent_router",
            self._after_router,
            {
                "conversational": "conversational",
                "knowledge": "knowledge",
                "places": "places",
            },
        )
        builder.add_edge("conversational", "output_guardrails")
        builder.add_edge("knowledge", "output_guardrails")
        builder.add_edge("places", "output_guardrails")
        builder.add_edge("output_guardrails", END)
        return builder.compile(checkpointer=self._checkpointer)

    @staticmethod
    def _after_input_guardrails(state: AgentState) -> str:
        return "finish" if state.get("blocked") else "route"

    @staticmethod
    def _after_router(state: AgentState) -> str:
        intent = state.get("intent")
        if intent in {"cultural_query", "food_culture"}:
            return "knowledge"
        if intent in {"restaurant_search", "navigation"}:
            return "places"
        return "conversational"

    @staticmethod
    def _new_turn_state(
        *,
        session_id: str,
        message: str,
        language: str,
        user_location: dict[str, float] | None,
        budget_filter: str | None,
        accessibility_required: bool,
    ) -> AgentState:
        """Reset all turn outputs while preserving checkpointed memory fields."""
        return {
            "session_id": session_id,
            "message": message,
            "language": language,
            "messages": [{"role": "user", "content": message}],
            "run_status": "planning",
            "current_step": "input_guardrails",
            "retry_count": 0,
            "error_code": None,
            "tool_calls": [],
            "tool_receipts": [],
            "pending_input": None,
            "reasoning_log": None,
            "intent": None,
            "intent_confidence": None,
            "is_followup": False,
            "needs_location": False,
            "response_text": "",
            "citations": [],
            "places": [],
            "suggestions": [],
            "guardrail_flags": {},
            "blocked": False,
            "knowledge_chunks": [],
            "user_location": user_location,
            "budget_filter": budget_filter,
            "accessibility_required": accessibility_required,
        }

    @staticmethod
    def _config(
        session_id: str,
        trace_config: dict[str, Any] | None = None,
        **values: Any,
    ) -> dict[str, Any]:
        return {
            **(trace_config or {}),
            "configurable": {"thread_id": session_id, **values},
        }

    @staticmethod
    def _result(
        state: dict[str, Any],
        langfuse_trace_id: str | None = None,
    ) -> GraphResult:
        interrupts = state.get("__interrupt__") or ()
        if interrupts:
            payload = getattr(interrupts[0], "value", interrupts[0])
            return GraphResult(
                response_text=str(payload.get("message", "")) if isinstance(payload, dict) else str(payload),
                intent=state.get("intent"),
                guardrail_flags=state.get("guardrail_flags", {}),
                interrupted=True,
                interrupt=payload if isinstance(payload, dict) else {"message": str(payload)},
                langfuse_trace_id=langfuse_trace_id,
            )
        return GraphResult(
            response_text=state.get("response_text", ""),
            suggestions=state.get("suggestions", []),
            citations=state.get("citations", []),
            places=state.get("places", []),
            intent=state.get("intent"),
            guardrail_flags=state.get("guardrail_flags", {}),
            blocked=bool(state.get("blocked")),
            reasoning_log=state.get("reasoning_log"),
            langfuse_trace_id=langfuse_trace_id,
        )

    async def answer(
        self,
        *,
        session_id: str,
        message: str,
        language: str = "vi",
        user_location: dict[str, float] | None = None,
        budget_filter: str | None = None,
        accessibility_required: bool = False,
    ) -> GraphResult:
        state = self._new_turn_state(
            session_id=session_id,
            message=message,
            language=language,
            user_location=user_location,
            budget_filter=budget_filter,
            accessibility_required=accessibility_required,
        )
        async with trace_graph_turn(
            langfuse_client=self._langfuse_client,
            session_id=session_id,
            operation="answer",
            input_data=state,
        ) as trace:
            config = self._config(
                session_id,
                trace.config,
                user_location=user_location,
                budget_filter=budget_filter,
                accessibility_required=accessibility_required,
            )
            final_state = await self.graph.ainvoke(state, config)
            trace.finish(final_state)
            return self._result(final_state, trace.trace_id)

    async def resume(self, *, session_id: str, resume_value: dict[str, Any]) -> GraphResult:
        async with trace_graph_turn(
            langfuse_client=self._langfuse_client,
            session_id=session_id,
            operation="resume",
            input_data={"resume": resume_value},
        ) as trace:
            state = await self.graph.ainvoke(
                Command(resume=resume_value),
                self._config(session_id, trace.config),
            )
            trace.finish(state)
            return self._result(state, trace.trace_id)

    async def stream_sse(
        self,
        *,
        session_id: str,
        message: str,
        language: str = "vi",
        user_location: dict[str, float] | None = None,
        budget_filter: str | None = None,
        accessibility_required: bool = False,
    ) -> AsyncGenerator[str, None]:
        from agents.graph.streaming import StreamingAdapter

        state = self._new_turn_state(
            session_id=session_id,
            message=message,
            language=language,
            user_location=user_location,
            budget_filter=budget_filter,
            accessibility_required=accessibility_required,
        )
        async with trace_graph_turn(
            langfuse_client=self._langfuse_client,
            session_id=session_id,
            operation="stream",
            input_data=state,
        ) as trace:
            config = self._config(
                session_id,
                trace.config,
                user_location=user_location,
                budget_filter=budget_filter,
                accessibility_required=accessibility_required,
            )
            adapter = StreamingAdapter()
            async for marker in adapter.adapt_stream(
                self.graph.astream(state, config, stream_mode=["updates", "custom"])
            ):
                yield marker

            snapshot = self.graph.get_state(config)
            final_state = dict(getattr(snapshot, "values", {}) or {})
            trace.finish(final_state)
            for task in getattr(snapshot, "tasks", ()) or ():
                for item in getattr(task, "interrupts", ()) or ():
                    payload = getattr(item, "value", None)
                    if isinstance(payload, dict):
                        yield "[STATUS] waiting_for_user_input"
                        yield f"[INTERRUPT] {json.dumps(payload, ensure_ascii=False)}"
                        return


async def create_ham_ninh_graph(
    checkpoint_mode: str = "memory",
    database_url: str | None = None,
    services: NodeServices | None = None,
    langfuse_client: Any | None = None,
) -> HamNinhGraph:
    if checkpoint_mode == "postgres":
        if not database_url:
            raise ValueError("database_url is required for postgres checkpointing")
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        checkpointer = AsyncPostgresSaver.from_conn_string(database_url)
    else:
        checkpointer = InMemorySaver()
    return HamNinhGraph(
        checkpointer=checkpointer,
        services=services,
        langfuse_client=langfuse_client,
    )
