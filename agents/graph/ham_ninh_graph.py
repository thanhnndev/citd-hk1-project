"""Single LangGraph runtime for the Ham Ninh assistant."""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import structlog
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
    NodeTimeoutError,
)

logger = structlog.get_logger(__name__)


def _with_timeout(node, name: str, seconds: int):
    """Apply one deterministic timeout policy to a graph node."""
    accepts_config = len(inspect.signature(node).parameters) >= 2

    async def wrapped(state: AgentState, config: Any = None) -> dict[str, Any]:
        try:
            call = node(state, config) if accepts_config else node(state)
            return await asyncio.wait_for(call, timeout=seconds)
        except asyncio.TimeoutError as exc:
            raise NodeTimeoutError(name, seconds) from exc

    return wrapped


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
            _with_timeout(input_guardrails_node, "input_guardrails", NODE_TIMEOUT_GUARDRAILS),
        )
        builder.add_node(
            "intent_router",
            _with_timeout(intent_router_node, "intent_router", NODE_TIMEOUT_ROUTER),
        )
        builder.add_node(
            "conversational",
            _with_timeout(conversational_node, "conversational", NODE_TIMEOUT_LLM),
        )
        builder.add_node(
            "knowledge",
            _with_timeout(rag_agent_node, "knowledge", NODE_TIMEOUT_LLM),
        )
        builder.add_node(
            "places",
            _with_timeout(maps_agent_node, "places", NODE_TIMEOUT_TOOL),
        )
        builder.add_node(
            "output_guardrails",
            _with_timeout(output_guardrails_node, "output_guardrails", NODE_TIMEOUT_GUARDRAILS),
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
        history: list[dict[str, str]] | None,
        user_location: dict[str, float] | None,
        budget_filter: str | None,
        accessibility_required: bool,
    ) -> AgentState:
        """Reset all turn outputs while preserving checkpointed memory fields."""
        return {
            "session_id": session_id,
            "message": message,
            "language": language,
            "history": history or [],
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
    def _config(session_id: str, **values: Any) -> dict[str, Any]:
        return {"configurable": {"thread_id": session_id, **values}}

    @staticmethod
    def _result(state: dict[str, Any]) -> GraphResult:
        interrupts = state.get("__interrupt__") or ()
        if interrupts:
            payload = getattr(interrupts[0], "value", interrupts[0])
            return GraphResult(
                response_text=str(payload.get("message", "")) if isinstance(payload, dict) else str(payload),
                intent=state.get("intent"),
                guardrail_flags=state.get("guardrail_flags", {}),
                interrupted=True,
                interrupt=payload if isinstance(payload, dict) else {"message": str(payload)},
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
        )

    async def answer(
        self,
        *,
        session_id: str,
        message: str,
        language: str = "vi",
        history: list[dict[str, str]] | None = None,
        user_location: dict[str, float] | None = None,
        budget_filter: str | None = None,
        accessibility_required: bool = False,
    ) -> GraphResult:
        state = self._new_turn_state(
            session_id=session_id,
            message=message,
            language=language,
            history=history,
            user_location=user_location,
            budget_filter=budget_filter,
            accessibility_required=accessibility_required,
        )
        config = self._config(
            session_id,
            user_location=user_location,
            budget_filter=budget_filter,
            accessibility_required=accessibility_required,
        )
        return self._result(await self.graph.ainvoke(state, config))

    async def resume(self, *, session_id: str, resume_value: dict[str, Any]) -> GraphResult:
        state = await self.graph.ainvoke(
            Command(resume=resume_value),
            self._config(session_id),
        )
        return self._result(state)

    async def stream_sse(
        self,
        *,
        session_id: str,
        message: str,
        language: str = "vi",
        history: list[dict[str, str]] | None = None,
        user_location: dict[str, float] | None = None,
        budget_filter: str | None = None,
        accessibility_required: bool = False,
    ) -> AsyncGenerator[str, None]:
        from agents.graph.streaming import StreamingAdapter

        state = self._new_turn_state(
            session_id=session_id,
            message=message,
            language=language,
            history=history,
            user_location=user_location,
            budget_filter=budget_filter,
            accessibility_required=accessibility_required,
        )
        config = self._config(
            session_id,
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
