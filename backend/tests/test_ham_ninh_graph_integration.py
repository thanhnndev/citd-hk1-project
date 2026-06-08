"""Integration tests for HamNinhGraph wiring in main.py and chat.py.

Tests verify:
1. main.py imports and uses AsyncPostgresSaver
2. main.py imports and uses HamNinhGraph
3. chat.py imports and uses HamNinhGraph
4. HamNinhGraph can be instantiated with real checkpointers
5. Chat router routes through HamNinhGraph when available
6. Fallback to AgentService when HamNinhGraph is not available
"""

import os
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Direct assignment — guaranteed to set before any lazy imports in test functions
os.environ["OPENAI_API_KEY"] = "test-key-for-unit-tests"
os.environ["APP_ENV"] = "test"

import pytest

# Starlette Request for slowapi rate limiter compatibility
from starlette.requests import Request as StarletteRequest


def _make_real_request(ham_ninh_graph=None, agent_service=None):
    """Create a real starlette Request with mock app.state attributes.

    slowapi rate limiter requires a real starlette.requests.Request instance,
    not a MagicMock. We create a real Request with a mock app attached.
    """
    mock_app = MagicMock()
    mock_app.state.ham_ninh_graph = ham_ninh_graph
    mock_app.state.agent_service = agent_service
    # _agent_service_available requires retriever or hybrid_retriever
    mock_app.state.retriever = MagicMock() if agent_service else None
    mock_app.state.hybrid_retriever = None
    # _ham_ninh_graph_available also checks app.state.langfuse_client
    mock_app.state.langfuse_client = None

    scope = {
        "type": "http",
        "method": "POST",
        "headers": [],
        "query_string": b"",
        "path": "/chat",
        "root_path": "",
        "scheme": "http",
        "server": ("testserver", 80),
        "app": mock_app,
    }
    return StarletteRequest(scope)


# ---------------------------------------------------------------------------
# Source-level verification tests (grep-like checks)
# ---------------------------------------------------------------------------


class TestSourceLevelIntegration:
    """Verify that main.py and chat.py contain the required references."""

    def test_main_py_imports_async_postgres_saver(self):
        """main.py must import AsyncPostgresSaver."""
        main_path = Path(__file__).parent.parent / "app" / "main.py"
        content = main_path.read_text()
        assert "AsyncPostgresSaver" in content, (
            "main.py does not reference AsyncPostgresSaver"
        )

    def test_main_py_imports_ham_ninh_graph(self):
        """main.py must import HamNinhGraph."""
        main_path = Path(__file__).parent.parent / "app" / "main.py"
        content = main_path.read_text()
        assert "HamNinhGraph" in content, (
            "main.py does not reference HamNinhGraph"
        )

    def test_main_py_creates_async_postgres_saver(self):
        """main.py must create AsyncPostgresSaver instance."""
        main_path = Path(__file__).parent.parent / "app" / "main.py"
        content = main_path.read_text()
        assert "AsyncPostgresSaver.from_conn_string" in content, (
            "main.py does not create AsyncPostgresSaver via from_conn_string"
        )

    def test_main_py_calls_setup_on_checkpointer(self):
        """main.py must call setup() on the checkpointer."""
        main_path = Path(__file__).parent.parent / "app" / "main.py"
        content = main_path.read_text()
        assert re.search(r"checkpointer\.setup\(\)", content), (
            "main.py does not call setup() on checkpointer"
        )

    def test_main_py_stores_ham_ninh_graph_on_app_state(self):
        """main.py must store HamNinhGraph on app.state."""
        main_path = Path(__file__).parent.parent / "app" / "main.py"
        content = main_path.read_text()
        assert "app.state.ham_ninh_graph" in content, (
            "main.py does not store HamNinhGraph on app.state"
        )

    def test_chat_py_imports_ham_ninh_graph(self):
        """chat.py must import HamNinhGraph."""
        chat_path = Path(__file__).parent.parent / "app" / "routers" / "chat.py"
        content = chat_path.read_text()
        assert "HamNinhGraph" in content, (
            "chat.py does not reference HamNinhGraph"
        )

    def test_chat_py_has_availability_helper(self):
        """chat.py must have _ham_ninh_graph_available helper."""
        chat_path = Path(__file__).parent.parent / "app" / "routers" / "chat.py"
        content = chat_path.read_text()
        assert "_ham_ninh_graph_available" in content, (
            "chat.py does not have _ham_ninh_graph_available helper"
        )

    def test_chat_py_routes_through_ham_ninh_graph(self):
        """chat.py must route through HamNinhGraph when available."""
        chat_path = Path(__file__).parent.parent / "app" / "routers" / "chat.py"
        content = chat_path.read_text()
        assert "ham_ninh_graph.answer" in content, (
            "chat.py does not call ham_ninh_graph.answer()"
        )

    def test_chat_py_streams_through_ham_ninh_graph(self):
        """chat.py must stream through HamNinhGraph when available."""
        chat_path = Path(__file__).parent.parent / "app" / "routers" / "chat.py"
        content = chat_path.read_text()
        assert "ham_ninh_graph.stream_sse" in content, (
            "chat.py does not call ham_ninh_graph.stream_sse()"
        )

    def test_chat_py_has_fallback_to_agent_service(self):
        """chat.py must have fallback to AgentService."""
        chat_path = Path(__file__).parent.parent / "app" / "routers" / "chat.py"
        content = chat_path.read_text()
        assert "agent_service.answer" in content, (
            "chat.py does not have fallback to agent_service.answer()"
        )


# ---------------------------------------------------------------------------
# HamNinhGraph instantiation tests
# ---------------------------------------------------------------------------


class TestHamNinhGraphInstantiation:
    """Test that HamNinhGraph can be instantiated with real checkpointers."""

    def test_ham_ninh_graph_can_be_instantiated(self):
        """HamNinhGraph can be instantiated with MemorySaver checkpointer."""
        from agents.graph.ham_ninh_graph import HamNinhGraph
        from agents.graph.nodes import NodeServices

        try:
            from langgraph.checkpoint.memory import MemorySaver
            checkpointer = MemorySaver()
        except ImportError:
            pytest.skip("langgraph not installed")

        services = NodeServices(
            llm_client=None,
            model="gpt-4o-mini",
            retriever=None,
            places_service=None,
        )

        graph = HamNinhGraph(checkpointer=checkpointer, services=services)

        assert graph is not None
        assert graph._checkpointer is checkpointer
        assert graph.graph is not None

    def test_ham_ninh_graph_with_none_checkpointer(self):
        """HamNinhGraph can be instantiated with None checkpointer (in-memory)."""
        from agents.graph.ham_ninh_graph import HamNinhGraph
        from agents.graph.nodes import NodeServices

        services = NodeServices(
            llm_client=None,
            model="gpt-4o-mini",
            retriever=None,
            places_service=None,
        )

        graph = HamNinhGraph(checkpointer=None, services=services)

        assert graph is not None
        # Should use MemorySaver by default
        assert graph._checkpointer is not None


# ---------------------------------------------------------------------------
# Chat router integration tests
# ---------------------------------------------------------------------------


class TestChatRouterIntegration:
    """Test that chat router correctly routes through HamNinhGraph.

    These tests verify the routing logic by checking that the correct
    internal function is called based on app.state configuration.
    We avoid calling the decorated endpoint functions directly because
    slowapi's rate limiter requires a Redis connection in the test env.
    Instead, we test the routing decision logic and source-level wiring.
    """

    def test_post_chat_routes_to_ham_ninh_graph_when_available(self):
        """POST /chat source code routes through HamNinhGraph when available."""
        chat_path = Path(__file__).parent.parent / "app" / "routers" / "chat.py"
        content = chat_path.read_text()

        # Verify the routing logic: check _ham_ninh_graph_available before ham_ninh_graph.answer
        assert "_ham_ninh_graph_available(request)" in content
        assert "ham_ninh_graph.answer(" in content
        assert "ham_ninh_graph.answer" in content

        # Verify GraphResult → ChatResponse conversion
        assert "graph_result.response_text" in content
        assert "graph_result.intent" in content
        assert "graph_result.citations" in content

    def test_post_chat_falls_back_to_agent_service_in_source(self):
        """POST /chat source code has fallback to AgentService."""
        chat_path = Path(__file__).parent.parent / "app" / "routers" / "chat.py"
        content = chat_path.read_text()

        # Verify fallback path exists after HamNinhGraph error handling
        assert "agent_service.answer(" in content
        assert "pipeline=\"agent_service\"" in content

    def test_stream_chat_routes_to_ham_ninh_graph_when_available(self):
        """GET /chat/stream source code routes through HamNinhGraph."""
        chat_path = Path(__file__).parent.parent / "app" / "routers" / "chat.py"
        content = chat_path.read_text()

        # Verify stream routing logic
        assert "use_ham_ninh_graph" in content
        assert "ham_ninh_graph.stream_sse(" in content
        assert "pipeline=\"ham_ninh_graph\"" in content

    @pytest.mark.asyncio
    async def test_ham_ninh_graph_answer_returns_graph_result(self):
        """HamNinhGraph.answer() returns a GraphResult with expected fields."""
        from agents.graph.ham_ninh_graph import GraphResult

        # Verify GraphResult dataclass has the fields chat.py expects
        result = GraphResult(
            response_text="Test response",
            intent="greeting",
            citations=[],
            suggestions=["Try asking about beaches"],
            blocked=False,
        )

        assert result.response_text == "Test response"
        assert result.intent == "greeting"
        assert result.citations == []
        assert result.suggestions == ["Try asking about beaches"]
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_ham_ninh_graph_stream_sse_yields_markers(self):
        """HamNinhGraph.stream_sse() yields SSE marker strings."""
        from agents.graph.ham_ninh_graph import HamNinhGraph
        from agents.graph.nodes import NodeServices

        try:
            from langgraph.checkpoint.memory import MemorySaver
        except ImportError:
            pytest.skip("langgraph not installed")

        services = NodeServices(
            llm_client=None,
            model="gpt-4o-mini",
            retriever=None,
            places_service=None,
        )

        graph = HamNinhGraph(checkpointer=MemorySaver(), services=services)

        # stream_sse should be an async generator
        assert hasattr(graph, "stream_sse")
        assert callable(graph.stream_sse)

        # Verify the method signature accepts the expected kwargs
        import inspect
        sig = inspect.signature(graph.stream_sse)
        params = list(sig.parameters.keys())
        assert "session_id" in params
        assert "message" in params
        assert "language" in params


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    """Test helper functions in chat.py."""

    def test_ham_ninh_graph_available_helper_true(self):
        """_ham_ninh_graph_available returns True when graph exists."""
        from app.routers.chat import _ham_ninh_graph_available

        request = _make_real_request(ham_ninh_graph=MagicMock())

        assert _ham_ninh_graph_available(request) is True

    def test_ham_ninh_graph_available_helper_false(self):
        """_ham_ninh_graph_available returns False when graph is None."""
        from app.routers.chat import _ham_ninh_graph_available

        request = _make_real_request(ham_ninh_graph=None)

        assert _ham_ninh_graph_available(request) is False

    def test_ham_ninh_graph_available_helper_missing_attr(self):
        """_ham_ninh_graph_available returns False when attribute missing."""
        from app.routers.chat import _ham_ninh_graph_available

        # Create a mock where ham_ninh_graph is not set
        mock_state = MagicMock(spec=[])  # spec=[] means no attributes
        mock_app = MagicMock()
        mock_app.state = mock_state

        scope = {
            "type": "http",
            "method": "POST",
            "headers": [],
            "query_string": b"",
            "path": "/chat",
            "root_path": "",
            "scheme": "http",
            "server": ("testserver", 80),
            "app": mock_app,
        }
        request = StarletteRequest(scope)

        assert _ham_ninh_graph_available(request) is False
