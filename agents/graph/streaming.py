"""Streaming adapter for LangGraph StateGraph events to SSE markers.

Maps LangGraph's astream() output (updates + custom modes) to the frontend's
expected SSE markers: [STATUS], [PLACES], [CITATIONS], [SUGGESTIONS], [DONE], [ERROR].
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import structlog

from agents.graph.state import AgentState, NodeTimeoutError

logger = structlog.get_logger(__name__)


class StreamingAdapter:
    """Adapts LangGraph stream events to SSE marker strings.

    Usage:
        adapter = StreamingAdapter()
        async for sse_marker in adapter.adapt_stream(graph_stream):
            yield sse_marker
    """

    def __init__(self) -> None:
        self._last_state_update: dict[str, Any] = {}
        self._response_text_emitted: bool = False

    async def adapt_stream(
        self, graph_stream: AsyncGenerator[dict[str, Any], None]
    ) -> AsyncGenerator[str, None]:
        """Map LangGraph astream() events to SSE markers.

        Args:
            graph_stream: Output from graph.astream(state, config,
                stream_mode=['updates', 'custom'], version='v2')

        Yields:
            SSE marker strings: [STATUS], [PLACES], [CITATIONS], [SUGGESTIONS],
            [INTERRUPT], response text, or [ERROR] messages.
        """
        try:
            async for chunk in graph_stream:
                chunk_type = chunk.get("type")

                if chunk_type == "updates":
                    # Node state update
                    async for event in self._handle_update(chunk):
                        yield event
                elif chunk_type == "custom":
                    # Custom stream events from get_stream_writer()
                    async for event in self._handle_custom(chunk):
                        yield event
                elif chunk_type == "interrupt":
                    # LangGraph interrupt - graph paused, waiting for user input
                    async for event in self._handle_interrupt(chunk):
                        yield event
                # Ignore other chunk types (e.g., 'values' for final state)

            # After stream completes, extract final state markers
            async for event in self._emit_final_markers():
                yield event

        except NodeTimeoutError as exc:
            logger.error(
                "graph.node_timeout",
                node_name=exc.node_name,
                timeout_seconds=exc.timeout_seconds,
            )
            yield f"[ERROR] Node '{exc.node_name}' timed out. Please try again."
        except Exception as exc:
            error_type = type(exc).__name__
            logger.error("graph.execution_error", error_type=error_type, error=str(exc))
            yield f"[ERROR] {error_type}"

    async def _handle_update(self, chunk: dict[str, Any]) -> AsyncGenerator[str, None]:
        """Handle 'updates' stream mode chunks (node state updates)."""
        data = chunk.get("data", {})

        # LangGraph v2 format: data is {node_name: state_update}
        for node_name, state_update in data.items():
            if not isinstance(state_update, dict):
                continue

            # Store for final state extraction
            self._last_state_update.update(state_update)

            # Map node updates to status markers
            async for event in self._map_node_to_status(node_name, state_update):
                yield event

    async def _map_node_to_status(
        self, node_name: str, state_update: dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        """Map specific node updates to SSE status markers."""

        if node_name == "input_guardrails":
            if state_update.get("guardrail_blocked"):
                yield "[STATUS] blocked"
            else:
                yield "[STATUS] validating"

        elif node_name == "intent_router":
            intent = state_update.get("intent", "unknown")
            confidence = state_update.get("intent_confidence")
            if confidence is not None:
                yield f"[STATUS] routing:{intent}:{confidence:.2f}"
            else:
                yield f"[STATUS] routing:{intent}"

        elif node_name == "supervisor":
            next_node = state_update.get("next_node", "unknown")
            yield f"[STATUS] dispatching:{next_node}"
                
        elif node_name == "conversational":
            response_text = state_update.get("response_text")
            if response_text:
                self._response_text_emitted = True
                yield response_text
                
        elif node_name == "rag_agent":
            yield "[STATUS] processing:rag"
            response_text = state_update.get("response_text")
            if response_text:
                self._response_text_emitted = True
                yield response_text
            
        elif node_name == "maps_agent":
            yield "[STATUS] processing:maps"
            response_text = state_update.get("response_text")
            if response_text:
                self._response_text_emitted = True
                yield response_text

        elif node_name == "output_guardrails":
            yield "[STATUS] verifying"

        # Other nodes: no status marker (silent)

    async def _handle_custom(self, chunk: dict[str, Any]) -> AsyncGenerator[str, None]:
        """Handle 'custom' stream mode chunks (get_stream_writer() events)."""
        data = chunk.get("data", {})
        event_type = data.get("type")

        if event_type == "token":
            # Token-by-token streaming from LLM
            content = data.get("content", "")
            if content:
                yield content
        elif event_type == "status":
            # Custom status updates from nodes
            content = data.get("content", "")
            if content:
                yield f"[STATUS] {content}"
        else:
            # Pass through other custom events as JSON
            # Nodes can emit arbitrary structured data
            if data:
                yield f"[CUSTOM] {json.dumps(data, ensure_ascii=False)}"

    async def _handle_interrupt(self, chunk: dict[str, Any]) -> AsyncGenerator[str, None]:
        """Handle 'interrupt' stream mode chunks (LangGraph interrupt() calls).

        When a node calls interrupt(), the graph pauses and emits an interrupt
        event. The frontend should detect this and provide the requested input
        (e.g., geolocation), then resume the graph.
        """
        data = chunk.get("data", {})
        if data:
            # Emit interrupt event with the interrupt payload
            yield f"[INTERRUPT] {json.dumps(data, ensure_ascii=False)}"

    async def _emit_final_markers(self) -> AsyncGenerator[str, None]:
        """Emit response_text (if not already streamed), [PLACES], [CITATIONS], [SUGGESTIONS] from final state."""
        state = self._last_state_update
        
        # Response text — safety net for nodes that didn't emit inline
        if not self._response_text_emitted:
            response_text = state.get("response_text")
            if response_text:
                self._response_text_emitted = True
                yield response_text
        
        # Places
        places = state.get("places")
        if places:
            # Convert to serializable format
            places_data = []
            for place in places:
                if hasattr(place, "model_dump"):
                    places_data.append(place.model_dump())
                elif isinstance(place, dict):
                    places_data.append(place)
                else:
                    places_data.append(str(place))
            yield f"[PLACES] {json.dumps(places_data, ensure_ascii=False)}"

        # Citations
        citations = state.get("citations")
        if citations:
            citations_data = []
            for citation in citations:
                if hasattr(citation, "model_dump"):
                    citations_data.append(citation.model_dump())
                elif isinstance(citation, dict):
                    citations_data.append(citation)
                else:
                    citations_data.append(str(citation))
            yield f"[CITATIONS] {json.dumps(citations_data, ensure_ascii=False)}"

        # Suggestions
        suggestions = state.get("suggestions")
        if suggestions:
            yield f"[SUGGESTIONS] {json.dumps(suggestions, ensure_ascii=False)}"


# ---------------------------------------------------------------------------
# Custom stream event helpers for use inside node functions
# ---------------------------------------------------------------------------


def emit_token(writer: Any, content: str) -> None:
    """Emit a token event via LangGraph's custom stream channel.

    Usage inside a node:
        from langgraph.config import get_stream_writer
        writer = get_stream_writer()
        emit_token(writer, "Hello")
    """
    writer({"type": "token", "content": content})


def emit_status(writer: Any, content: str) -> None:
    """Emit a status event via LangGraph's custom stream channel.

    Usage inside a node:
        from langgraph.config import get_stream_writer
        writer = get_stream_writer()
        emit_status(writer, "routing")
    """
    writer({"type": "status", "content": content})


def emit_custom(writer: Any, data: dict[str, Any]) -> None:
    """Emit an arbitrary custom event via LangGraph's custom stream channel.

    The data dict is passed through as-is to the frontend.
    """
    writer(data)


async def stream_graph_to_sse(
    graph: Any,
    state: AgentState,
    config: dict[str, Any],
) -> AsyncGenerator[str, None]:
    """Convenience function: stream a graph and adapt to SSE markers.

    Args:
        graph: LangGraph CompiledStateGraph instance
        state: Initial AgentState
        config: LangGraph config dict (includes thread_id, etc.)

    Yields:
        SSE marker strings ready for the chat.py SSE wrapper.
    """
    adapter = StreamingAdapter()

    try:
        # Stream with updates + custom modes for full observability
        graph_stream = graph.astream(
            state,
            config,
            stream_mode=["updates", "custom"],
            version="v2",
        )

        async for event in adapter.adapt_stream(graph_stream):
            yield event

    except Exception as exc:
        # Catch-all for graph execution failures
        error_type = type(exc).__name__
        logger.error(
            "graph.stream_failed",
            error_type=error_type,
            error=str(exc),
            session_id=state.get("session_id"),
        )
        yield f"[ERROR] {error_type}"
