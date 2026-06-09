"""HamNinhGraph — LangGraph StateGraph assembler with per-node timeout policy.

This module assembles the full agent pipeline as a LangGraph StateGraph with:
- 9 nodes (8 real + 1 stub) from agents.graph.nodes
- Per-node TimeoutPolicy via asyncio.wait_for
- Conditional routing based on supervisor decisions
- AsyncPostgresSaver or MemorySaver checkpointing

The graph topology:
    START → input_guardrails → (conditional: blocked → END, else → intent_router)
    intent_router → supervisor → (conditional routing)
        → conversational → output_guardrails → END
        → rag_agent → grade_documents → (conditional) → output_guardrails → END
        → maps_agent → output_guardrails → END
        → output_guardrails → END (direct block)

TimeoutPolicy:
    Each node is wrapped with asyncio.wait_for(node_timeout).
    On timeout: raises NodeTimeoutError, logs structured event, returns error state.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Literal

import structlog

from agents.graph.state import (
    AgentState,
    NodeTimeoutError,
    NODE_TIMEOUT_GRADE,
    NODE_TIMEOUT_GUARDRAILS,
    NODE_TIMEOUT_INTENT_ROUTER,
    NODE_TIMEOUT_LLM,
    NODE_TIMEOUT_TOOL,
    NODE_TIMEOUT_RETRIEVE,
    NODE_TIMEOUT_REWRITE,
    NODE_TIMEOUT_SEMANTIC_FALLBACK,
)
from agents.graph.nodes import (
    NodeServices,
    configure_services,
    input_guardrails_node,
    intent_router_node,
    supervisor_node,
    conversational_node,
    output_guardrails_node,
    rag_agent_node,
    grade_documents_node,
    rewrite_query_node,
    maps_agent_node,
)

try:
    from langfuse import Langfuse, propagate_attributes
except Exception:  # pragma: no cover - optional runtime dependency
    Langfuse = None
    propagate_attributes = None

try:
    from langgraph.graph import END, START, StateGraph
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.errors import GraphInterrupt
    from langgraph.types import Command
except Exception:  # pragma: no cover - optional runtime dependency
    END = "__end__"
    START = "__start__"
    StateGraph = None
    MemorySaver = None
    GraphInterrupt = None
    Command = None

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# TimeoutPolicy — per-node timeout configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TimeoutPolicy:
    """Per-node timeout policy.

    Each node has a maximum execution time in seconds. If exceeded,
    the wrapper raises ``NodeTimeoutError`` and logs a structured event.
    """

    timeouts: dict[str, int] = field(default_factory=lambda: {
        "input_guardrails": NODE_TIMEOUT_GUARDRAILS,
        "intent_router": NODE_TIMEOUT_INTENT_ROUTER,
        "supervisor": NODE_TIMEOUT_INTENT_ROUTER,  # Same tier as router
        "conversational": NODE_TIMEOUT_LLM,
        "output_guardrails": NODE_TIMEOUT_GUARDRAILS,
        "rag_agent": NODE_TIMEOUT_LLM,
        "grade_documents": NODE_TIMEOUT_GRADE,
        "rewrite_query": NODE_TIMEOUT_REWRITE,
        "maps_agent": NODE_TIMEOUT_TOOL,
    })

    def get(self, node_name: str) -> int:
        """Return the timeout for a node, defaulting to 10s."""
        return self.timeouts.get(node_name, 10)


# ---------------------------------------------------------------------------
# Timeout wrapper
# ---------------------------------------------------------------------------


def _wrap_with_timeout(node_fn, node_name: str, timeout_seconds: int):
    """Wrap an async node function with asyncio.wait_for timeout.

    On timeout:
        - Logs ``graph.timeout`` with node_name and timeout_seconds
        - Raises ``NodeTimeoutError`` (caught by graph executor)

    Returns:
        Wrapped async function with the same signature as node_fn.
    """
    import functools
    sig = inspect.signature(node_fn)
    params = list(sig.parameters.values())

    if len(params) >= 2:
        @functools.wraps(node_fn)
        async def wrapper_with_config(state: AgentState, config: Any) -> dict[str, Any]:
            try:
                return await asyncio.wait_for(node_fn(state, config), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                logger.error(
                    "graph.timeout",
                    node_name=node_name,
                    timeout_seconds=timeout_seconds,
                )
                raise NodeTimeoutError(node_name, timeout_seconds)
            except Exception as exc:
                # Re-raise non-timeout exceptions with context
                logger.error(
                    "graph.node_error",
                    node_name=node_name,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                raise
        return wrapper_with_config
    else:
        @functools.wraps(node_fn)
        async def wrapper(state: AgentState) -> dict[str, Any]:
            try:
                return await asyncio.wait_for(node_fn(state), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                logger.error(
                    "graph.timeout",
                    node_name=node_name,
                    timeout_seconds=timeout_seconds,
                )
                raise NodeTimeoutError(node_name, timeout_seconds)
            except Exception as exc:
                # Re-raise non-timeout exceptions with context
                logger.error(
                    "graph.node_error",
                    node_name=node_name,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                raise
        return wrapper


# ---------------------------------------------------------------------------
# Graph result container
# ---------------------------------------------------------------------------


@dataclass
class GraphResult:
    """Container for graph execution results.

    Returned by ``HamNinhGraph.answer()`` with the final state fields.
    """

    response_text: str = ""
    suggestions: list[str] = field(default_factory=list)
    citations: list[Any] = field(default_factory=list)
    places: list[Any] = field(default_factory=list)
    intent: str | None = None
    routing_tier: str | None = None
    guardrail_flags: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False
    langfuse_trace_id: str | None = None
    reasoning_log: str | None = None
    guardrail_status: str | None = None
    interrupted: bool = False
    interrupt: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# HamNinhGraph — main graph assembler
# ---------------------------------------------------------------------------


class HamNinhGraph:
    """LangGraph StateGraph assembler for the Ham Ninh tourism agent.

    Assembles the full graph topology with per-node TimeoutPolicy and
    conditional routing. Supports both in-memory and Postgres checkpointing.

    Usage:
        graph = HamNinhGraph(checkpointer=MemorySaver())
        result = await graph.answer(
            session_id="user-123",
            message="Xin chào",
            language="vi",
        )
        print(result.response_text)

    Attributes:
        graph: The compiled LangGraph CompiledStateGraph instance.
    """

    def __init__(
        self,
        checkpointer: Any = None,
        services: NodeServices | None = None,
        langfuse_client: Any | None = None,
    ) -> None:
        """Initialize and compile the StateGraph.

        Args:
            checkpointer: LangGraph checkpoint saver (MemorySaver or AsyncPostgresSaver).
                Defaults to MemorySaver if None.
            services: Optional NodeServices for dependency injection into nodes.
                If provided, calls configure_services() before compilation.
            langfuse_client: Optional Langfuse client for tracing. When provided,
                creates CallbackHandler for automatic graph topology tracing.
        """
        if StateGraph is None:
            raise RuntimeError("langgraph is not installed")

        # Configure node services if provided
        if services is not None:
            configure_services(services)

        # Default to in-memory checkpointing
        if checkpointer is None:
            checkpointer = MemorySaver() if MemorySaver is not None else None

        self._checkpointer = checkpointer
        self._timeout_policy = TimeoutPolicy()
        self._langfuse_client = langfuse_client

        # Build and compile the graph
        self.graph = self._build_graph()

        logger.info(
            "graph.compiled",
            checkpoint_mode=type(checkpointer).__name__ if checkpointer else "none",
            node_count=9,
        )

    def _build_graph(self) -> Any:
        """Assemble the StateGraph topology with all nodes and edges.

        Returns:
            CompiledStateGraph ready for execution.
        """
        builder = StateGraph(AgentState)

        # Add all nodes with timeout wrappers
        nodes = [
            ("input_guardrails", input_guardrails_node),
            ("intent_router", intent_router_node),
            ("supervisor", supervisor_node),
            ("conversational", conversational_node),
            ("output_guardrails", output_guardrails_node),
            ("rag_agent", rag_agent_node),
            ("grade_documents", grade_documents_node),
            ("rewrite_query", rewrite_query_node),
            ("maps_agent", maps_agent_node),
        ]

        for node_name, node_fn in nodes:
            timeout = self._timeout_policy.get(node_name)
            wrapped = _wrap_with_timeout(node_fn, node_name, timeout)
            builder.add_node(node_name, wrapped)

        # Guardrails must finish before intent routing. Running both from START
        # allows blocked input and routing updates to race into the supervisor.
        builder.add_edge(START, "input_guardrails")
        builder.add_conditional_edges(
            "input_guardrails",
            self._route_after_guardrails,
            {
                "intent_router": "intent_router",
                "output_guardrails": "output_guardrails",
            },
        )
        builder.add_edge("intent_router", "supervisor")

        # Conditional edge: supervisor → (conversational | rag_agent | maps_agent | output_guardrails)
        builder.add_conditional_edges(
            "supervisor",
            self._route_after_supervisor,
            {
                "conversational": "conversational",
                "rag_agent": "rag_agent",
                "maps_agent": "maps_agent",
                "output_guardrails": "output_guardrails",
            },
        )

        # Fixed edges: processing nodes → next step
        builder.add_edge("conversational", "output_guardrails")
        builder.add_edge("rag_agent", "grade_documents")
        builder.add_edge("maps_agent", "output_guardrails")

        # Conditional edge: grade_documents → (rewrite_query | output_guardrails)
        builder.add_conditional_edges(
            "grade_documents",
            self._route_after_grade,
            {
                "rewrite_query": "rewrite_query",
                "output_guardrails": "output_guardrails",
            },
        )

        # Back-edge: rewrite_query → rag_agent (self-corrective loop)
        builder.add_edge("rewrite_query", "rag_agent")

        # Final edge: output_guardrails → END
        builder.add_edge("output_guardrails", END)

        # Compile with checkpointer
        return builder.compile(checkpointer=self._checkpointer)

    @staticmethod
    def _route_after_guardrails(state: AgentState) -> str:
        """Routing function: after input_guardrails node.

        If guardrails blocked (intent == 'blocked' or 'off_topic'), route to END.
        Otherwise, continue to intent_router.

        Args:
            state: Current AgentState after input_guardrails execution.

        Returns:
            Next node name: "intent_router" or "output_guardrails".
        """
        intent = state.get("intent")
        if intent in ("blocked", "off_topic"):
            return "output_guardrails"
        return "intent_router"

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
        """Build a turn delta that explicitly clears checkpointed turn output."""
        return {
            "run_status": "planning",
            "current_step": "understand_request",
            "error_code": None,
            "retry_count": 0,
            "session_id": session_id,
            "message": message,
            "language": language,
            "history": history or [],
            "messages": [{"role": "user", "content": message}],
            "tool_calls": [],
            "citations": [],
            "places": [],
            "suggestions": [],
            "reasoning_log": None,
            "intent": None,
            "intent_confidence": None,
            "is_followup": False,
            "routing_tier": None,
            "needs_location": False,
            "next_node": None,
            "guardrail_flags": {},
            "response_text": "",
            "langfuse_trace_id": None,
            "knowledge_chunks": [],
            "knowledge_response_ready": False,
            "grade_score": None,
            "grade_label": None,
            "rewrite_count": 0,
            "rewritten_query": None,
            "user_location": user_location,
            "budget_filter": budget_filter,
            "accessibility_required": accessibility_required,
            "blocked": False,
        }

    @staticmethod
    def _route_after_grade(state: AgentState) -> str:
        """Routing function: after grade_documents node.

        Routes to rewrite_query when grade_label == 'irrelevant' and
        rewrite_count < 1 (max one rewrite attempt). Otherwise routes
        to output_guardrails.

        Args:
            state: Current AgentState after grade_documents execution.

        Returns:
            Next node name: "rewrite_query" or "output_guardrails".
        """
        grade_label = state.get("grade_label")
        rewrite_count = state.get("rewrite_count", 0)

        if grade_label == "irrelevant" and rewrite_count < 1:
            return "rewrite_query"
        return "output_guardrails"

    @staticmethod
    def _route_after_supervisor(state: AgentState) -> str:
        """Routing function: after supervisor node.

        Reads ``state["next_node"]`` set by supervisor and returns it.
        Defaults to "conversational" if next_node is not set.

        Args:
            state: Current AgentState after supervisor execution.

        Returns:
            Next node name: "conversational", "rag_agent", "maps_agent", or "output_guardrails".
        """
        next_node = state.get("next_node", "conversational")
        return next_node

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
        """Execute the graph and return a structured result.

        This is the primary entry point for synchronous graph execution.
        For streaming, use ``stream_sse()`` instead.

        Args:
            session_id: Unique session identifier for checkpointing.
            message: User's input message.
            language: Language code ("vi" or "en").
            history: Optional conversation history (overrides checkpoint).

        Returns:
            GraphResult with response_text, suggestions, citations, places, etc.

        Raises:
            NodeTimeoutError: If a node exceeds its timeout (logged and re-raised).
        """
        # Build initial state as a delta over checkpointed memory.
        # Keep prior checkpointed messages/history intact and only inject the
        # current turn plus any fresh request fields.
        state = self._new_turn_state(
            session_id=session_id,
            message=message,
            language=language,
            history=history,
            user_location=user_location,
            budget_filter=budget_filter,
            accessibility_required=accessibility_required,
        )

        # Config with thread_id for checkpointing and static parameters
        config = {
            "configurable": {
                "thread_id": session_id,
                "user_location": user_location,
                "budget_filter": budget_filter,
                "accessibility_required": accessibility_required,
            }
        }

        # Add Langfuse CallbackHandler if client is present
        trace_id = None
        langfuse_enabled = self._langfuse_client is not None and Langfuse is not None

        try:
            # Execute the graph. Langfuse docs recommend propagating trace
            # attributes around the runnable so child LangChain observations
            # stay attached to one trace.
            if langfuse_enabled and propagate_attributes is not None:
                with propagate_attributes(
                    trace_name="ham-ninh-graph",
                    session_id=session_id,
                    metadata={"langfuse_session_id": session_id},
                    tags=["ham-ninh-graph", "chat"],
                ):
                    try:
                        from langfuse.langchain import CallbackHandler
                        config["callbacks"] = [CallbackHandler()]
                        config["tags"] = ["ham-ninh-graph", "chat"]
                        config["metadata"] = {"langfuse_session_id": session_id}
                        logger.debug("langfuse.callback_created", session_id=session_id)
                    except Exception as exc:
                        logger.warning(
                            "langfuse.callback_failed",
                            error_type=type(exc).__name__,
                            error=str(exc),
                        )
                        config.pop("callbacks", None)
                    final_state = await self.graph.ainvoke(state, config)
                    if "callbacks" in config:
                        try:
                            trace_id = self._langfuse_client.get_current_trace_id()
                        except Exception:
                            trace_id = None
                    else:
                        trace_id = None
            else:
                final_state = await self.graph.ainvoke(state, config)

            interrupt_value = self._pending_interrupt(config)
            if interrupt_value is not None:
                response_text = str(interrupt_value.get("message") or "")
                return GraphResult(
                    response_text=response_text,
                    suggestions=[],
                    citations=[],
                    places=[],
                    intent=final_state.get("intent"),
                    routing_tier=final_state.get("routing_tier"),
                    guardrail_flags=final_state.get("guardrail_flags", {}),
                    blocked=False,
                    langfuse_trace_id=trace_id,
                    interrupted=True,
                    interrupt=interrupt_value,
                )

            # Extract result fields
            return GraphResult(
                response_text=final_state.get("response_text", ""),
                suggestions=final_state.get("suggestions", []),
                citations=final_state.get("citations", []),
                places=final_state.get("places", []),
                intent=final_state.get("intent"),
                routing_tier=final_state.get("routing_tier"),
                guardrail_flags=final_state.get("guardrail_flags", {}),
                blocked=final_state.get("intent") in ("blocked", "off_topic"),
                langfuse_trace_id=trace_id,
            )

        except NodeTimeoutError as exc:
            # Timeout already logged by wrapper, re-raise
            logger.error(
                "graph.execution_timeout",
                session_id=session_id,
                node_name=exc.node_name,
                timeout_seconds=exc.timeout_seconds,
            )
            raise

    def _pending_interrupt(self, config: dict[str, Any]) -> dict[str, Any] | None:
        """Return the first pending LangGraph interrupt payload for this thread.

        Per LangGraph docs, ``interrupt()`` pauses execution and stores the
        pending task in the checkpoint. Callers must inspect graph state and
        resume with ``Command(resume=...)`` instead of treating empty output as
        a failed answer.
        """
        try:
            graph_state = self.graph.get_state(config)
        except Exception:
            return None

        for task in getattr(graph_state, "tasks", ()) or ():
            for interrupt_obj in getattr(task, "interrupts", ()) or ():
                value = getattr(interrupt_obj, "value", None)
                if isinstance(value, dict):
                    return value
        return None

    async def resume(self, *, session_id: str, resume_value: dict[str, Any]) -> GraphResult:
        """Resume a paused graph with ``Command(resume=...)``.

        This is the documented LangGraph interrupt lifecycle: a node calls
        ``interrupt(payload)``, the UI collects user input, then the graph is
        resumed with that value on the same ``thread_id``.
        """
        if Command is None:
            raise RuntimeError("langgraph Command is not available")

        config = {"configurable": {"thread_id": session_id}}
        final_state = await self.graph.ainvoke(Command(resume=resume_value), config)
        interrupt_value = self._pending_interrupt(config)
        if interrupt_value is not None:
            return GraphResult(
                response_text=str(interrupt_value.get("message") or ""),
                intent=final_state.get("intent"),
                routing_tier=final_state.get("routing_tier"),
                guardrail_flags=final_state.get("guardrail_flags", {}),
                interrupted=True,
                interrupt=interrupt_value,
            )

        return GraphResult(
            response_text=final_state.get("response_text", ""),
            suggestions=final_state.get("suggestions", []),
            citations=final_state.get("citations", []),
            places=final_state.get("places", []),
            intent=final_state.get("intent"),
            routing_tier=final_state.get("routing_tier"),
            guardrail_flags=final_state.get("guardrail_flags", {}),
            blocked=final_state.get("intent") in ("blocked", "off_topic"),
        )

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
        """Execute the graph with streaming and yield SSE markers.

        Uses the StreamingAdapter to convert LangGraph stream events to
        SSE marker strings: [STATUS], [PLACES], [CITATIONS], [SUGGESTIONS], etc.

        Args:
            session_id: Unique session identifier for checkpointing.
            message: User's input message.
            language: Language code ("vi" or "en").
            history: Optional conversation history (overrides checkpoint).

        Yields:
            SSE marker strings ready for the chat.py SSE wrapper.
        """
        from agents.graph.streaming import StreamingAdapter

        # Build initial state as a delta over checkpointed memory.
        # Keep prior checkpointed messages/history intact and only inject the
        # current turn plus any fresh request fields.
        state = self._new_turn_state(
            session_id=session_id,
            message=message,
            language=language,
            history=history,
            user_location=user_location,
            budget_filter=budget_filter,
            accessibility_required=accessibility_required,
        )

        # Config with thread_id for checkpointing and static parameters
        config = {
            "configurable": {
                "thread_id": session_id,
                "user_location": user_location,
                "budget_filter": budget_filter,
                "accessibility_required": accessibility_required,
            }
        }

        # Stream with updates + custom modes for full observability
        adapter = StreamingAdapter()
        stream_interrupted = False

        try:
            langfuse_enabled = self._langfuse_client is not None and Langfuse is not None
            if langfuse_enabled and propagate_attributes is not None:
                with propagate_attributes(
                    trace_name="ham-ninh-graph-stream",
                    session_id=session_id,
                    metadata={"langfuse_session_id": session_id},
                    tags=["ham-ninh-graph", "chat", "stream"],
                ):
                    try:
                        from langfuse.langchain import CallbackHandler
                        config["callbacks"] = [CallbackHandler()]
                        config["tags"] = ["ham-ninh-graph", "chat", "stream"]
                        config["metadata"] = {"langfuse_session_id": session_id}
                        logger.debug("langfuse.callback_created_stream", session_id=session_id)
                    except Exception as exc:
                        logger.warning(
                            "langfuse.callback_failed_stream",
                            error_type=type(exc).__name__,
                            error=str(exc),
                        )
                        config.pop("callbacks", None)
                    graph_stream = self.graph.astream(
                        state,
                        config,
                        stream_mode=["updates", "custom"],
                        version="v2",
                    )
                    async for sse_marker in adapter.adapt_stream(graph_stream):
                        yield sse_marker
            else:
                graph_stream = self.graph.astream(
                    state,
                    config,
                    stream_mode=["updates", "custom"],
                    version="v2",
                )
                async for sse_marker in adapter.adapt_stream(graph_stream):
                    yield sse_marker

            # After stream completes, check if graph was interrupted
            # LangGraph's astream() doesn't raise GraphInterrupt - it stops normally
            # We need to check the final state for pending interrupts
            final_state = self.graph.get_state(config)
            if final_state.next:  # Has pending tasks = interrupted
                # Extract interrupt value from tasks
                for task in final_state.tasks:
                    if hasattr(task, 'interrupts') and task.interrupts:
                        for interrupt_obj in task.interrupts:
                            if hasattr(interrupt_obj, 'value'):
                                interrupt_value = interrupt_obj.value
                                logger.info(
                                    "graph.interrupt_detected",
                                    session_id=session_id,
                                    interrupt_type=interrupt_value.get("type"),
                                    requires_geolocation=interrupt_value.get("requires_geolocation"),
                                )
                                yield "[STATUS] waiting_for_user_input"
                                yield f"[INTERRUPT] {json.dumps(interrupt_value)}"
                                stream_interrupted = True
                                break
                    if stream_interrupted:
                        break

        except NodeTimeoutError as exc:
            logger.error(
                "graph.stream_timeout",
                session_id=session_id,
                node_name=exc.node_name,
                timeout_seconds=exc.timeout_seconds,
            )
            yield "[STATUS] failed-recoverable"
            yield f"[ERROR] Node '{exc.node_name}' timed out. Please try again."

        except Exception as exc:
            error_type = type(exc).__name__
            logger.error(
                "graph.stream_error",
                session_id=session_id,
                error_type=error_type,
                error=str(exc),
            )
            yield "[STATUS] failed-recoverable"
            yield f"[ERROR] {error_type}"


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


async def create_ham_ninh_graph(
    checkpoint_mode: Literal["memory", "postgres"] = "memory",
    database_url: str | None = None,
    services: NodeServices | None = None,
    langfuse_client: Any | None = None,
) -> HamNinhGraph:
    """Factory function to create a HamNinhGraph with the specified checkpointer.

    Args:
        checkpoint_mode: "memory" for in-memory, "postgres" for AsyncPostgresSaver.
        database_url: PostgreSQL connection string (required if checkpoint_mode="postgres").
        services: Optional NodeServices for dependency injection.
        langfuse_client: Optional Langfuse client for tracing graph topology.

    Returns:
        Configured HamNinhGraph instance.

    Raises:
        ValueError: If checkpoint_mode="postgres" but database_url is None.
    """
    if checkpoint_mode == "postgres":
        if database_url is None:
            raise ValueError("database_url required for postgres checkpoint mode")

        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            checkpointer = AsyncPostgresSaver.from_conn_string(database_url)
            logger.info("graph.checkpoint_mode", mode="postgres")
        except ImportError:
            logger.warning(
                "graph.postgres_saver_unavailable",
                fallback="memory",
            )
            checkpointer = MemorySaver() if MemorySaver is not None else None
    else:
        checkpointer = MemorySaver() if MemorySaver is not None else None
        logger.info("graph.checkpoint_mode", mode="memory")

    return HamNinhGraph(checkpointer=checkpointer, services=services, langfuse_client=langfuse_client)
