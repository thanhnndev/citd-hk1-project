"""Tests for Langfuse CallbackHandler wiring in HamNinhGraph.

Verifies that:
- CallbackHandler is created when langfuse_client is present
- No callback is created when langfuse_client is absent
- trace_id is extracted and added to GraphResult
- Graceful degradation when CallbackHandler creation fails
- stream_sse also wires CallbackHandler
- Factory function passes langfuse_client through
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.graph.ham_ninh_graph import GraphResult, HamNinhGraph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_langfuse_client(public_key: str = "pk-test-123") -> MagicMock:
    """Create a mock Langfuse client with public_key and get_current_trace_id."""
    client = MagicMock()
    client.public_key = public_key
    client.secret_key = "sk-test-456"
    client.host = "https://cloud.langfuse.com"
    client.get_current_trace_id.return_value = "trace-abc-123"
    return client


def _make_final_state(**overrides) -> dict:
    """Create a minimal final state dict returned by graph.ainvoke."""
    state = {
        "response_text": "Xin chào!",
        "suggestions": ["suggestion1"],
        "citations": [],
        "places": [],
        "intent": "conversational",
        "routing_tier": "strict",
        "guardrail_flags": {},
        "langfuse_trace_id": None,
    }
    state.update(overrides)
    return state


async def _empty_async_iter():
    """Async generator that yields nothing (for mocking astream)."""
    return
    yield  # pragma: no cover — makes this an async generator


def _make_graph_with_mock(langfuse_client=None):
    """Create a HamNinhGraph with mocked graph execution."""
    g = HamNinhGraph(langfuse_client=langfuse_client)
    # Mock graph.ainvoke (awaited → AsyncMock)
    g.graph = MagicMock()
    g.graph.ainvoke = AsyncMock(return_value=_make_final_state())
    # Mock graph.astream (NOT awaited → regular MagicMock returning async gen)
    g.graph.astream = MagicMock(return_value=_empty_async_iter())
    return g


# ---------------------------------------------------------------------------
# Test: CallbackHandler created when client present
# ---------------------------------------------------------------------------


class TestCallbackHandlerCreated:
    """When langfuse_client is present, CallbackHandler is created and passed in config."""

    @pytest.mark.asyncio
    async def test_callback_handler_created_when_client_present(self):
        """CallbackHandler is instantiated and added to config callbacks."""
        client = _make_mock_langfuse_client()
        g = _make_graph_with_mock(langfuse_client=client)

        result = await g.answer(session_id="sess-001", message="test")

        # The config passed to ainvoke should contain callbacks
        call_args = g.graph.ainvoke.call_args
        config = call_args[0][1]  # Second positional arg is config
        assert "callbacks" in config, "callbacks should be in config when langfuse_client present"
        assert len(config["callbacks"]) == 1, "Should have exactly one callback handler"

    @pytest.mark.asyncio
    async def test_callback_handler_is_langchain_handler(self):
        """The callback in config is a real LangchainCallbackHandler."""
        client = _make_mock_langfuse_client()
        g = _make_graph_with_mock(langfuse_client=client)

        await g.answer(session_id="sess-002", message="test key")

        call_args = g.graph.ainvoke.call_args
        config = call_args[0][1]
        handler = config["callbacks"][0]
        # Verify it's a real Langchain callback handler (has on_chain_start, etc.)
        assert hasattr(handler, "on_chain_start")
        assert hasattr(handler, "on_chain_end")
        assert hasattr(handler, "on_llm_start")


# ---------------------------------------------------------------------------
# Test: No callback when client absent
# ---------------------------------------------------------------------------


class TestNoCallbackWhenAbsent:
    """When langfuse_client is None, no CallbackHandler is created."""

    @pytest.mark.asyncio
    async def test_no_callback_when_client_absent(self):
        """No callbacks key in config when langfuse_client is None."""
        g = _make_graph_with_mock(langfuse_client=None)

        result = await g.answer(session_id="sess-003", message="test no client")

        call_args = g.graph.ainvoke.call_args
        config = call_args[0][1]
        assert "callbacks" not in config, "callbacks should NOT be in config when langfuse_client is None"

    @pytest.mark.asyncio
    async def test_graph_result_trace_id_none_when_no_client(self):
        """GraphResult.langfuse_trace_id is None when no langfuse_client."""
        g = _make_graph_with_mock(langfuse_client=None)

        result = await g.answer(session_id="sess-004", message="test trace id none")

        assert result.langfuse_trace_id is None


# ---------------------------------------------------------------------------
# Test: trace_id added to GraphResult
# ---------------------------------------------------------------------------


class TestTraceIdInGraphResult:
    """trace_id is extracted from langfuse client and added to GraphResult."""

    @pytest.mark.asyncio
    async def test_trace_id_added_to_graph_result(self):
        """GraphResult.langfuse_trace_id is set from client.get_current_trace_id()."""
        client = _make_mock_langfuse_client()
        g = _make_graph_with_mock(langfuse_client=client)

        result = await g.answer(session_id="sess-005", message="test trace id")

        assert result.langfuse_trace_id == "trace-abc-123"
        client.get_current_trace_id.assert_called_once()

    @pytest.mark.asyncio
    async def test_trace_id_extraction_failure_graceful(self):
        """When get_current_trace_id fails, GraphResult still returned with trace_id=None."""
        client = _make_mock_langfuse_client()
        client.get_current_trace_id.side_effect = RuntimeError("trace not available")

        g = _make_graph_with_mock(langfuse_client=client)

        result = await g.answer(session_id="sess-006", message="test trace fail")

        assert result.langfuse_trace_id is None
        assert result.response_text == "Xin chào!"


# ---------------------------------------------------------------------------
# Test: GraphResult dataclass has langfuse_trace_id field
# ---------------------------------------------------------------------------


class TestGraphResultDataclass:
    """GraphResult dataclass includes langfuse_trace_id field."""

    def test_graph_result_has_langfuse_trace_id_field(self):
        """GraphResult has langfuse_trace_id with default None."""
        result = GraphResult()
        assert hasattr(result, "langfuse_trace_id")
        assert result.langfuse_trace_id is None

    def test_graph_result_accepts_trace_id(self):
        """GraphResult can be constructed with langfuse_trace_id."""
        result = GraphResult(
            response_text="test",
            langfuse_trace_id="trace-xyz-789",
        )
        assert result.langfuse_trace_id == "trace-xyz-789"
        assert result.response_text == "test"


# ---------------------------------------------------------------------------
# Test: Constructor accepts langfuse_client
# ---------------------------------------------------------------------------


class TestConstructor:
    """HamNinhGraph constructor accepts and stores langfuse_client."""

    def test_constructor_stores_langfuse_client(self):
        """langfuse_client is stored as self._langfuse_client."""
        client = _make_mock_langfuse_client()
        g = HamNinhGraph(langfuse_client=client)
        assert g._langfuse_client is client

    def test_constructor_default_no_client(self):
        """Without langfuse_client, self._langfuse_client is None."""
        g = HamNinhGraph()
        assert g._langfuse_client is None

    def test_constructor_explicit_none(self):
        """Explicit langfuse_client=None stores None."""
        g = HamNinhGraph(langfuse_client=None)
        assert g._langfuse_client is None


# ---------------------------------------------------------------------------
# Test: stream_sse also wires CallbackHandler
# ---------------------------------------------------------------------------


class TestStreamSseWiring:
    """stream_sse also creates CallbackHandler when langfuse_client present."""

    @pytest.mark.asyncio
    async def test_stream_sse_adds_callback_when_client_present(self):
        """stream_sse adds CallbackHandler to config when langfuse_client present."""
        client = _make_mock_langfuse_client()
        g = _make_graph_with_mock(langfuse_client=client)

        # stream_sse imports StreamingAdapter internally — mock it to avoid
        # dependency on the streaming module's adapt_stream implementation
        with patch("agents.graph.ham_ninh_graph.StreamingAdapter", create=True) as mock_adapter_cls:
            mock_adapter = MagicMock()

            async def _empty_adapt(stream):
                return
                yield  # pragma: no cover

            mock_adapter.adapt_stream = _empty_adapt
            mock_adapter_cls.return_value = mock_adapter

            markers = []
            async for marker in g.stream_sse(session_id="sess-007", message="test stream"):
                markers.append(marker)

        # Verify astream was called with config containing callbacks
        call_args = g.graph.astream.call_args
        config = call_args[0][1]  # Second positional arg is config
        assert "callbacks" in config, "callbacks should be in stream config when langfuse_client present"

    @pytest.mark.asyncio
    async def test_stream_sse_no_callback_when_client_absent(self):
        """stream_sse does not add callbacks when langfuse_client is None."""
        g = _make_graph_with_mock(langfuse_client=None)

        with patch("agents.graph.ham_ninh_graph.StreamingAdapter", create=True) as mock_adapter_cls:
            mock_adapter = MagicMock()

            async def _empty_adapt(stream):
                return
                yield  # pragma: no cover

            mock_adapter.adapt_stream = _empty_adapt
            mock_adapter_cls.return_value = mock_adapter

            markers = []
            async for marker in g.stream_sse(session_id="sess-008", message="test stream no client"):
                markers.append(marker)

        call_args = g.graph.astream.call_args
        config = call_args[0][1]
        assert "callbacks" not in config, "callbacks should NOT be in stream config when no langfuse_client"


# ---------------------------------------------------------------------------
# Test: Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """When langfuse_client is None or CallbackHandler creation fails, no crashes."""

    @pytest.mark.asyncio
    async def test_no_crash_without_client(self):
        """answer() completes successfully without langfuse_client."""
        g = _make_graph_with_mock(langfuse_client=None)

        result = await g.answer(session_id="sess-009", message="test no crash")

        assert result.response_text == "Xin chào!"
        assert result.langfuse_trace_id is None

    @pytest.mark.asyncio
    async def test_callback_creation_error_does_not_crash(self):
        """If CallbackHandler import/creation fails, graph still executes."""
        client = _make_mock_langfuse_client()
        g = _make_graph_with_mock(langfuse_client=client)

        # Patch the import to fail by temporarily removing the module
        # and making the import raise
        import builtins
        original_import = builtins.__import__

        def failing_import(name, *args, **kwargs):
            if name == "langfuse.langchain":
                raise ImportError("langfuse.langchain not available")
            return original_import(name, *args, **kwargs)

        # Remove cached module so the import is re-triggered
        saved = sys.modules.pop("langfuse.langchain", None)
        builtins.__import__ = failing_import
        try:
            result = await g.answer(session_id="sess-010", message="test import fail")
            # Should still succeed, just without tracing
            assert result.response_text == "Xin chào!"
            assert result.langfuse_trace_id is None

            # Config should NOT have callbacks since handler creation failed
            call_args = g.graph.ainvoke.call_args
            config = call_args[0][1]
            assert "callbacks" not in config
        finally:
            builtins.__import__ = original_import
            if saved is not None:
                sys.modules["langfuse.langchain"] = saved


# ---------------------------------------------------------------------------
# Test: Factory function passes langfuse_client
# ---------------------------------------------------------------------------


class TestFactoryFunction:
    """create_ham_ninh_graph accepts and passes langfuse_client."""

    @pytest.mark.asyncio
    async def test_factory_accepts_langfuse_client(self):
        """Factory function accepts langfuse_client parameter."""
        from agents.graph.ham_ninh_graph import create_ham_ninh_graph

        client = _make_mock_langfuse_client()
        g = await create_ham_ninh_graph(
            checkpoint_mode="memory",
            langfuse_client=client,
        )
        assert g._langfuse_client is client

    @pytest.mark.asyncio
    async def test_factory_default_no_client(self):
        """Factory function defaults to no langfuse_client."""
        from agents.graph.ham_ninh_graph import create_ham_ninh_graph

        g = await create_ham_ninh_graph(checkpoint_mode="memory")
        assert g._langfuse_client is None
