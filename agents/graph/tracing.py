"""Langfuse tracing boundary for one LangGraph user turn."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict, is_dataclass
from typing import Any, AsyncIterator

from pydantic import BaseModel


def to_trace_value(value: Any) -> Any:
    """Convert graph state values into JSON-compatible trace data."""
    if isinstance(value, BaseModel):
        return to_trace_value(value.model_dump(mode="json"))
    if is_dataclass(value):
        return to_trace_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_trace_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_trace_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return to_trace_value(model_dump(mode="json"))
    return str(value)


class GraphTrace:
    """Mutable trace context used while a graph invocation is active."""

    def __init__(
        self,
        *,
        config: dict[str, Any],
        trace_id: str | None = None,
        observation: Any | None = None,
    ) -> None:
        self.config = config
        self.trace_id = trace_id
        self._observation = observation

    def finish(self, state: dict[str, Any]) -> None:
        """Attach the complete final graph state to the root request trace."""
        if self._observation is None:
            return
        output = {
            "response": state.get("response_text", ""),
            "state": to_trace_value(state),
        }
        self._observation.update(output=output)
        self._observation.set_trace_io(output=output)


@asynccontextmanager
async def trace_graph_turn(
    *,
    langfuse_client: Any | None,
    session_id: str,
    operation: str,
    input_data: dict[str, Any],
) -> AsyncIterator[GraphTrace]:
    """Create one root Langfuse trace and nest the full LangGraph run under it."""
    base_config: dict[str, Any] = {
        "run_name": "ham-ninh-graph",
        "tags": ["langgraph", operation],
        "metadata": {
            "langfuse_session_id": session_id,
            "operation": operation,
        },
    }
    if langfuse_client is None:
        yield GraphTrace(config=base_config)
        return

    from langfuse import propagate_attributes
    from langfuse.langchain import CallbackHandler

    trace_input = to_trace_value(input_data)
    with langfuse_client.start_as_current_observation(
        name="ham-ninh-request",
        as_type="agent",
        input=trace_input,
        metadata={"operation": operation},
    ) as observation:
        with propagate_attributes(
            session_id=session_id,
            trace_name="ham-ninh-request",
            tags=["langgraph", operation],
            metadata={"operation": operation},
        ):
            observation.set_trace_io(input=trace_input)
            handler = CallbackHandler()
            config = {
                **base_config,
                "callbacks": [handler],
            }
            trace = GraphTrace(
                config=config,
                trace_id=langfuse_client.get_current_trace_id(),
                observation=observation,
            )
            try:
                yield trace
            except Exception as exc:
                observation.update(
                    level="ERROR",
                    status_message=str(exc),
                    metadata={
                        "operation": operation,
                        "error_type": type(exc).__name__,
                    },
                )
                raise
