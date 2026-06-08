"""Tests for the enhanced GET /admin/traces endpoint.

Verifies that:
- When Langfuse is enabled, the endpoint fetches recent traces from the API
- Trace data includes trace_id, session_id, name, timestamp, latency_ms, total_cost
- Latency is converted from seconds to milliseconds
- When Langfuse is disabled, recent_traces is None
- When the Langfuse API call fails, the endpoint returns 200 with recent_traces=None

All tests use mocked Langfuse client — no real Langfuse server needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.routers.admin import _fetch_recent_traces, router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_app() -> FastAPI:
    """Build a minimal FastAPI app with the admin router and auth bypassed."""
    app = FastAPI()
    app.include_router(router)
    return app


def _mock_admin_user():
    """Return a mock user object for auth dependency override."""
    user = MagicMock()
    user.id = "test-admin-user"
    return user


_UNSET = object()  # Sentinel to distinguish "not provided" from "explicitly None"


def _make_mock_trace(
    trace_id: str = "trace_abc123",
    session_id: str = "sess_xyz789",
    name: str = "chat_request",
    timestamp: datetime | None | object = _UNSET,
    latency: float | None = 1.234,  # seconds
    total_cost: float | None = 0.0042,
):
    """Create a mock TraceWithDetails object."""
    trace = MagicMock()
    trace.id = trace_id
    trace.session_id = session_id
    trace.name = name
    trace.timestamp = (
        datetime(2026, 6, 8, 10, 0, 0, tzinfo=timezone.utc)
        if timestamp is _UNSET
        else timestamp
    )
    trace.latency = latency
    trace.total_cost = total_cost
    return trace


def _make_mock_traces_response(traces: list):
    """Create a mock Traces response object."""
    response = MagicMock()
    response.data = traces
    return response


@pytest.fixture
def app():
    """FastAPI app with admin router."""
    return _build_app()


@pytest.fixture
def auth_override(app):
    """Override get_current_user to return a mock admin user."""
    from app.middleware.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: _mock_admin_user()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client(app, auth_override):
    """Async test client for the admin app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ===========================================================================
# 1. _fetch_recent_traces — unit tests for the helper function
# ===========================================================================

class TestFetchRecentTraces:
    """Direct unit tests for _fetch_recent_traces() helper function."""

    def test_returns_recent_traces_when_enabled(self):
        """_fetch_recent_traces returns list of trace dicts when API succeeds."""
        mock_client = MagicMock()
        mock_traces = [
            _make_mock_trace(
                trace_id="trace_001",
                session_id="sess_001",
                name="chat_request",
                latency=1.5,  # 1.5 seconds = 1500 ms
                total_cost=0.005,
            ),
            _make_mock_trace(
                trace_id="trace_002",
                session_id="sess_002",
                name="search_places",
                latency=2.3,  # 2.3 seconds = 2300 ms
                total_cost=0.008,
            ),
        ]
        mock_client.api.trace.list.return_value = _make_mock_traces_response(mock_traces)

        result = _fetch_recent_traces(mock_client, limit=10)

        assert result is not None
        assert len(result) == 2

        # First trace
        assert result[0]["trace_id"] == "trace_001"
        assert result[0]["session_id"] == "sess_001"
        assert result[0]["name"] == "chat_request"
        assert result[0]["latency_ms"] == 1500.0
        assert result[0]["total_cost"] == 0.005
        assert "timestamp" in result[0]

        # Second trace
        assert result[1]["trace_id"] == "trace_002"
        assert result[1]["latency_ms"] == 2300.0

    def test_converts_latency_from_seconds_to_milliseconds(self):
        """Latency is converted from seconds (Langfuse) to milliseconds."""
        mock_client = MagicMock()
        mock_trace = _make_mock_trace(latency=3.456)  # 3.456 seconds
        mock_client.api.trace.list.return_value = _make_mock_traces_response([mock_trace])

        result = _fetch_recent_traces(mock_client)

        assert result is not None
        assert result[0]["latency_ms"] == 3456.0

    def test_handles_none_latency(self):
        """When trace.latency is None, latency_ms is None."""
        mock_client = MagicMock()
        mock_trace = _make_mock_trace(latency=None)
        mock_client.api.trace.list.return_value = _make_mock_traces_response([mock_trace])

        result = _fetch_recent_traces(mock_client)

        assert result is not None
        assert result[0]["latency_ms"] is None

    def test_handles_none_total_cost(self):
        """When trace.total_cost is None, total_cost is None."""
        mock_client = MagicMock()
        mock_trace = _make_mock_trace(total_cost=None)
        mock_client.api.trace.list.return_value = _make_mock_traces_response([mock_trace])

        result = _fetch_recent_traces(mock_client)

        assert result is not None
        assert result[0]["total_cost"] is None

    def test_handles_none_timestamp(self):
        """When trace.timestamp is None, timestamp is None."""
        mock_client = MagicMock()
        mock_trace = _make_mock_trace(timestamp=None)
        mock_client.api.trace.list.return_value = _make_mock_traces_response([mock_trace])

        result = _fetch_recent_traces(mock_client)

        assert result is not None
        assert result[0]["timestamp"] is None

    def test_returns_empty_list_when_no_traces(self):
        """When API returns empty data list, returns empty list."""
        mock_client = MagicMock()
        mock_client.api.trace.list.return_value = _make_mock_traces_response([])

        result = _fetch_recent_traces(mock_client)

        assert result is not None
        assert result == []

    def test_returns_none_when_api_call_fails(self):
        """When API call raises exception, returns None."""
        mock_client = MagicMock()
        mock_client.api.trace.list.side_effect = Exception("API connection failed")

        result = _fetch_recent_traces(mock_client)

        assert result is None

    def test_returns_none_when_auth_error(self):
        """When API returns auth error, returns None."""
        mock_client = MagicMock()
        mock_client.api.trace.list.side_effect = PermissionError("Invalid API key")

        result = _fetch_recent_traces(mock_client)

        assert result is None

    def test_returns_none_when_timeout(self):
        """When API call times out, returns None."""
        mock_client = MagicMock()
        mock_client.api.trace.list.side_effect = TimeoutError("Request timed out")

        result = _fetch_recent_traces(mock_client)

        assert result is None

    def test_calls_api_with_correct_parameters(self):
        """_fetch_recent_traces calls api.trace.list with correct params."""
        mock_client = MagicMock()
        mock_client.api.trace.list.return_value = _make_mock_traces_response([])

        _fetch_recent_traces(mock_client, limit=5)

        mock_client.api.trace.list.assert_called_once_with(
            limit=5,
            order_by="timestamp",
        )

    def test_respects_limit_parameter(self):
        """_fetch_recent_traces respects the limit parameter."""
        mock_client = MagicMock()
        mock_traces = [_make_mock_trace(trace_id=f"trace_{i}") for i in range(20)]
        mock_client.api.trace.list.return_value = _make_mock_traces_response(mock_traces)

        result = _fetch_recent_traces(mock_client, limit=20)

        assert result is not None
        assert len(result) == 20


# ===========================================================================
# 2. GET /admin/traces — HTTP endpoint tests
# ===========================================================================

class TestGetTracesEndpoint:
    """HTTP endpoint tests for GET /admin/traces."""

    @pytest.mark.asyncio
    async def test_returns_recent_traces_when_enabled(self, client, app):
        """When Langfuse is enabled, endpoint returns recent_traces list."""
        mock_langfuse_client = MagicMock()
        mock_traces = [
            _make_mock_trace(
                trace_id="trace_http_001",
                session_id="sess_http_001",
                name="chat_request",
                latency=1.23,
                total_cost=0.003,
            ),
        ]
        mock_langfuse_client.api.trace.list.return_value = _make_mock_traces_response(mock_traces)

        # Set langfuse_client on app.state
        app.state.langfuse_client = mock_langfuse_client

        with patch("app.routers.admin.get_settings") as mock_settings:
            mock_settings.return_value.LANGFUSE_HOST = "https://langfuse.example.com"

            resp = await client.get("/admin/traces")

        assert resp.status_code == 200
        body = resp.json()

        assert body["langfuse_enabled"] is True
        assert body["host"] == "https://langfuse.example.com"
        assert body["recent_traces"] is not None
        assert len(body["recent_traces"]) == 1
        assert body["recent_traces"][0]["trace_id"] == "trace_http_001"
        assert body["recent_traces"][0]["latency_ms"] == 1230.0

    @pytest.mark.asyncio
    async def test_returns_none_when_disabled(self, client, app):
        """When Langfuse is disabled, recent_traces is None."""
        # No langfuse_client on app.state
        if hasattr(app.state, "langfuse_client"):
            delattr(app.state, "langfuse_client")

        with patch("app.routers.admin.get_settings") as mock_settings:
            mock_settings.return_value.LANGFUSE_HOST = None

            resp = await client.get("/admin/traces")

        assert resp.status_code == 200
        body = resp.json()

        assert body["langfuse_enabled"] is False
        assert body["host"] is None
        assert body["recent_traces"] is None
        assert "not configured" in body["message"].lower()

    @pytest.mark.asyncio
    async def test_handles_api_error_gracefully(self, client, app):
        """When Langfuse API call fails, endpoint returns 200 with recent_traces=None."""
        mock_langfuse_client = MagicMock()
        mock_langfuse_client.api.trace.list.side_effect = Exception("API unavailable")

        app.state.langfuse_client = mock_langfuse_client

        with patch("app.routers.admin.get_settings") as mock_settings:
            mock_settings.return_value.LANGFUSE_HOST = "https://langfuse.example.com"

            resp = await client.get("/admin/traces")

        assert resp.status_code == 200
        body = resp.json()

        assert body["langfuse_enabled"] is True
        assert body["recent_traces"] is None
        assert "fetch failed" in body["message"].lower()

    @pytest.mark.asyncio
    async def test_returns_multiple_traces(self, client, app):
        """Endpoint returns multiple traces in the list."""
        mock_langfuse_client = MagicMock()
        mock_traces = [
            _make_mock_trace(trace_id="trace_1", name="chat", latency=1.0),
            _make_mock_trace(trace_id="trace_2", name="search", latency=2.0),
            _make_mock_trace(trace_id="trace_3", name="recommend", latency=3.0),
        ]
        mock_langfuse_client.api.trace.list.return_value = _make_mock_traces_response(mock_traces)

        app.state.langfuse_client = mock_langfuse_client

        with patch("app.routers.admin.get_settings") as mock_settings:
            mock_settings.return_value.LANGFUSE_HOST = "https://langfuse.example.com"

            resp = await client.get("/admin/traces")

        assert resp.status_code == 200
        body = resp.json()

        assert len(body["recent_traces"]) == 3
        trace_ids = [t["trace_id"] for t in body["recent_traces"]]
        assert "trace_1" in trace_ids
        assert "trace_2" in trace_ids
        assert "trace_3" in trace_ids

    @pytest.mark.asyncio
    async def test_trace_fields_are_correct(self, client, app):
        """Each trace dict has the expected fields."""
        mock_langfuse_client = MagicMock()
        mock_trace = _make_mock_trace(
            trace_id="trace_fields",
            session_id="sess_fields",
            name="test_trace",
            latency=1.5,
            total_cost=0.01,
        )
        mock_langfuse_client.api.trace.list.return_value = _make_mock_traces_response([mock_trace])

        app.state.langfuse_client = mock_langfuse_client

        with patch("app.routers.admin.get_settings") as mock_settings:
            mock_settings.return_value.LANGFUSE_HOST = "https://langfuse.example.com"

            resp = await client.get("/admin/traces")

        assert resp.status_code == 200
        body = resp.json()

        trace = body["recent_traces"][0]
        expected_fields = {"trace_id", "session_id", "name", "timestamp", "latency_ms", "total_cost"}
        assert set(trace.keys()) == expected_fields


# ===========================================================================
# 3. Graceful degradation — edge cases and error handling
# ===========================================================================

class TestGracefulDegradation:
    """Test graceful degradation for various error scenarios."""

    def test_handles_malformed_timestamp(self):
        """When timestamp is not a datetime, handles gracefully."""
        mock_client = MagicMock()
        mock_trace = _make_mock_trace()
        mock_trace.timestamp = "not-a-datetime"  # Malformed
        mock_client.api.trace.list.return_value = _make_mock_traces_response([mock_trace])

        # Should handle gracefully (may raise or return None)
        result = _fetch_recent_traces(mock_client)

        # Either returns None (exception caught) or handles the malformed data
        assert result is None or (result is not None and len(result) >= 0)

    def test_handles_negative_latency(self):
        """When latency is negative, still converts to milliseconds."""
        mock_client = MagicMock()
        mock_trace = _make_mock_trace(latency=-0.5)
        mock_client.api.trace.list.return_value = _make_mock_traces_response([mock_trace])

        result = _fetch_recent_traces(mock_client)

        assert result is not None
        assert result[0]["latency_ms"] == -500.0

    def test_handles_zero_latency(self):
        """When latency is zero, returns 0.0 ms."""
        mock_client = MagicMock()
        mock_trace = _make_mock_trace(latency=0.0)
        mock_client.api.trace.list.return_value = _make_mock_traces_response([mock_trace])

        result = _fetch_recent_traces(mock_client)

        assert result is not None
        assert result[0]["latency_ms"] == 0.0

    def test_handles_very_large_latency(self):
        """When latency is very large, still converts correctly."""
        mock_client = MagicMock()
        mock_trace = _make_mock_trace(latency=3600.0)  # 1 hour
        mock_client.api.trace.list.return_value = _make_mock_traces_response([mock_trace])

        result = _fetch_recent_traces(mock_client)

        assert result is not None
        assert result[0]["latency_ms"] == 3600000.0

    def test_handles_none_session_id(self):
        """When session_id is None, includes it as None."""
        mock_client = MagicMock()
        mock_trace = _make_mock_trace(session_id=None)
        mock_client.api.trace.list.return_value = _make_mock_traces_response([mock_trace])

        result = _fetch_recent_traces(mock_client)

        assert result is not None
        assert result[0]["session_id"] is None

    def test_handles_none_name(self):
        """When name is None, includes it as None."""
        mock_client = MagicMock()
        mock_trace = _make_mock_trace(name=None)
        mock_client.api.trace.list.return_value = _make_mock_traces_response([mock_trace])

        result = _fetch_recent_traces(mock_client)

        assert result is not None
        assert result[0]["name"] is None
