"""Tests for trace_id propagation from GraphResult to ChatResponse.

Verifies that:
- chat.py source code wires langfuse_trace_id from GraphResult to ChatResponse
- GraphResult has the langfuse_trace_id field
- ChatResponse accepts and stores the langfuse_trace_id field
- When GraphResult.langfuse_trace_id is None, ChatResponse.langfuse_trace_id is also None

Note: We avoid calling the decorated endpoint functions directly because
slowapi's rate limiter requires a Redis connection in the test env.
Instead, we test the wiring via source-level checks and model validation.
"""

from pathlib import Path
import pytest


class TestSourceLevelWiring:
    """Verify chat.py contains the trace_id propagation wiring."""

    def test_chat_py_propagates_langfuse_trace_id(self):
        """chat.py must pass langfuse_trace_id from GraphResult to ChatResponse."""
        chat_path = Path(__file__).parent.parent / "app" / "routers" / "chat.py"
        content = chat_path.read_text()

        # Verify the trace_id is extracted from graph_result and passed to ChatResponse
        assert "langfuse_trace_id=graph_result.langfuse_trace_id" in content, (
            "chat.py does not propagate langfuse_trace_id from graph_result to ChatResponse"
        )

    def test_chat_py_passes_session_id_to_response(self):
        """chat.py must pass session_id to ChatResponse."""
        chat_path = Path(__file__).parent.parent / "app" / "routers" / "chat.py"
        content = chat_path.read_text()

        # Verify session_id is passed to ChatResponse
        assert "session_id=body.session_id" in content, (
            "chat.py does not pass session_id to ChatResponse"
        )


class TestGraphResultHasTraceIdField:
    """Verify GraphResult dataclass has langfuse_trace_id field."""

    def test_graph_result_has_langfuse_trace_id_field(self):
        """GraphResult must have langfuse_trace_id field."""
        from agents.graph.ham_ninh_graph import GraphResult

        # Create a GraphResult with a trace_id
        result = GraphResult(
            response_text="Test response",
            intent="test_intent",
            citations=[],
            suggestions=[],
            blocked=False,
            langfuse_trace_id="trace_xyz789",
        )

        assert hasattr(result, "langfuse_trace_id")
        assert result.langfuse_trace_id == "trace_xyz789"

    def test_graph_result_trace_id_defaults_to_none(self):
        """GraphResult.langfuse_trace_id defaults to None."""
        from agents.graph.ham_ninh_graph import GraphResult

        result = GraphResult(
            response_text="Test response",
            intent="test_intent",
            citations=[],
            suggestions=[],
            blocked=False,
        )

        assert result.langfuse_trace_id is None


class TestChatResponseAcceptsTraceId:
    """Verify ChatResponse model accepts langfuse_trace_id field."""

    def test_chat_response_accepts_langfuse_trace_id(self):
        """ChatResponse must accept langfuse_trace_id in constructor."""
        from app.models.response import ChatResponse

        response = ChatResponse(
            session_id="session_123",
            message="Test message",
            intent="test_intent",
            citations=[],
            suggestions=[],
            fallback=False,
            latency_ms=100.5,
            langfuse_trace_id="trace_abc123",
        )

        assert response.langfuse_trace_id == "trace_abc123"
        assert response.session_id == "session_123"

    def test_chat_response_trace_id_defaults_to_none(self):
        """ChatResponse.langfuse_trace_id defaults to None."""
        from app.models.response import ChatResponse

        response = ChatResponse(
            session_id="session_456",
            message="Test message",
            intent="test_intent",
            citations=[],
            suggestions=[],
            fallback=False,
            latency_ms=50.0,
        )

        assert response.langfuse_trace_id is None

    def test_chat_response_with_none_trace_id(self):
        """ChatResponse accepts None for langfuse_trace_id (Langfuse disabled)."""
        from app.models.response import ChatResponse

        response = ChatResponse(
            session_id="session_789",
            message="Test message",
            intent="test_intent",
            citations=[],
            suggestions=[],
            fallback=False,
            latency_ms=75.0,
            langfuse_trace_id=None,
        )

        assert response.langfuse_trace_id is None
