"""Tests for admin /traces and /fairness endpoints (S04 observability)."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Resolve project root so we can import agents.* regardless of cwd.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "backend"))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.admin import router as admin_router

# ---------------------------------------------------------------------------
# Test app setup
# ---------------------------------------------------------------------------

def _build_app(langfuse_client=None):
    """Build a minimal FastAPI with admin router for testing."""
    app = FastAPI()
    app.include_router(admin_router)
    app.state.bm25_vectorizer = None
    app.state.langfuse_client = langfuse_client

    mock_user = MagicMock()
    mock_user.id = "test-admin-user"
    mock_user.is_active = True
    mock_user_service = MagicMock()
    mock_user_service.get_by_id = AsyncMock(return_value=mock_user)
    app.state.user_service = mock_user_service

    return app


@pytest.fixture
def client_disabled():
    """TestClient with langfuse disabled."""
    return TestClient(_build_app(langfuse_client=None))


@pytest.fixture
def client_enabled():
    """TestClient with langfuse enabled."""
    return TestClient(_build_app(langfuse_client=MagicMock()))


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer fake-jwt-token-for-tests"}


@pytest.fixture
def no_auth_headers():
    return {}


@pytest.fixture
def mock_decode_token():
    """Mock JWT decode to accept any fake token."""
    with patch("app.middleware.auth.decode_access_token") as mock:
        mock.return_value = {"sub": "test-admin-user"}
        yield mock


# ---------------------------------------------------------------------------
# GET /admin/traces — Langfuse status
# ---------------------------------------------------------------------------

class TestAdminTracesLangfuseStatus:
    """Verify GET /admin/traces returns real Langfuse status."""

    def test_returns_disabled_when_no_client(
        self, client_disabled, auth_headers, mock_decode_token
    ):
        """When langfuse_client is None, report disabled."""
        with patch("app.routers.admin.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                LANGFUSE_HOST="http://langfuse:3000"
            )
            response = client_disabled.get("/admin/traces", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["langfuse_enabled"] is False
            assert data["host"] is None
            assert "LANGFUSE" in data["message"]

    def test_returns_enabled_when_client_present(
        self, client_enabled, auth_headers, mock_decode_token
    ):
        """When langfuse_client is not None, report enabled."""
        with patch("app.routers.admin.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                LANGFUSE_HOST="http://localhost:3000"
            )
            response = client_enabled.get("/admin/traces", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["langfuse_enabled"] is True
            assert data["host"] == "http://localhost:3000"
            assert "active" in data["message"].lower()


class TestAdminTracesAuth:
    """Verify JWT auth on GET /admin/traces."""

    def test_no_auth_returns_401(self, client_disabled, no_auth_headers):
        response = client_disabled.get("/admin/traces", headers=no_auth_headers)
        assert response.status_code == 401

    def test_invalid_token_returns_401(self, client_disabled):
        response = client_disabled.get(
            "/admin/traces",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /admin/fairness — Fairness audit summary
# ---------------------------------------------------------------------------

class TestAdminFairness:
    """Verify GET /admin/fairness returns fairness audit summary."""

    def _mock_audit_path(self, audit_dir: Path):
        """Return a context manager that patches Path so admin.py resolves to audit_dir."""
        mock_file_path = MagicMock()
        mock_dir = MagicMock()
        mock_dir.exists.return_value = audit_dir.exists()
        mock_dir.glob.return_value = list(audit_dir.glob("*.jsonl")) if audit_dir.exists() else []
        # Make mock_dir / "anything" return mock_dir itself (handles chained /)
        mock_dir.__truediv__ = MagicMock(return_value=mock_dir)

        def _mock_div(n):
            if n == 3:
                p = MagicMock()
                p.__truediv__ = MagicMock(return_value=mock_dir)
                return p
            return MagicMock()

        mock_file_path.parents = MagicMock()
        mock_file_path.parents.__getitem__ = MagicMock(side_effect=_mock_div)
        mock_file_path.resolve.return_value = mock_file_path
        return patch("app.routers.admin.Path", return_value=mock_file_path)

    def test_returns_empty_when_no_audit_dir(
        self, client_disabled, auth_headers, mock_decode_token, tmp_path
    ):
        """When data/fairness_audit/ doesn't exist, return zero audits."""
        # Point to a non-existent directory
        nonexistent = tmp_path / "nonexistent"
        with self._mock_audit_path(nonexistent):
            response = client_disabled.get("/admin/fairness", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["total_audits"] == 0
            assert "no fairness" in data["message"].lower()

    def test_returns_empty_when_dir_exists_but_no_files(
        self, client_disabled, auth_headers, mock_decode_token, tmp_path
    ):
        """When directory exists but has no JSONL files, return zero audits."""
        audit_dir = tmp_path / "fairness_audit"
        audit_dir.mkdir()
        with self._mock_audit_path(audit_dir):
            response = client_disabled.get("/admin/fairness", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["total_audits"] == 0

    def test_returns_audit_data_when_files_exist(
        self, client_disabled, auth_headers, mock_decode_token, tmp_path
    ):
        """When audit files exist, return count + latest_timestamp + distribution."""
        audit_dir = tmp_path / "fairness_audit"
        audit_dir.mkdir()

        # Write two audit files
        file1 = audit_dir / "audit_001.jsonl"
        file1.write_text(
            json.dumps({"local_factor": 0.9, "timestamp": "2026-01-01T00:00:00Z", "query": "test1"}) + "\n"
            + json.dumps({"local_factor": 0.3, "timestamp": "2026-01-01T00:01:00Z", "query": "test2"}) + "\n"
        )

        file2 = audit_dir / "audit_002.jsonl"
        file2.write_text(
            json.dumps({"local_factor": 0.6, "timestamp": "2026-01-02T00:00:00Z", "query": "test3"}) + "\n"
        )

        with self._mock_audit_path(audit_dir):
            response = client_disabled.get("/admin/fairness", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["total_audits"] == 2
            assert data["latest_timestamp"] is not None
            assert data["local_factor_distribution"] is not None
            dist = data["local_factor_distribution"]
            assert "buckets" in dist
            assert "mean" in dist
            assert "count" in dist

    def test_requires_auth(self, client_disabled, no_auth_headers):
        response = client_disabled.get("/admin/fairness", headers=no_auth_headers)
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Response model tests
# ---------------------------------------------------------------------------

class TestTracesFairnessModels:
    """Verify TracesStatusResponse and FairnessSummaryResponse serialize."""

    def test_traces_status_enabled(self):
        from app.models.response import TracesStatusResponse

        resp = TracesStatusResponse(
            langfuse_enabled=True,
            host="http://localhost:3000",
            message="Langfuse tracing is active.",
        )
        data = resp.model_dump()
        assert data["langfuse_enabled"] is True
        assert data["host"] == "http://localhost:3000"

    def test_traces_status_disabled(self):
        from app.models.response import TracesStatusResponse

        resp = TracesStatusResponse(
            langfuse_enabled=False,
            host=None,
            message="Langfuse not configured.",
        )
        data = resp.model_dump()
        assert data["langfuse_enabled"] is False
        assert data["host"] is None

    def test_fairness_summary_with_data(self):
        from app.models.response import FairnessSummaryResponse

        resp = FairnessSummaryResponse(
            total_audits=5,
            latest_timestamp="2026-01-01T00:00:00+00:00",
            local_factor_distribution={
                "buckets": {"<0.1": 0, "0.1-0.3": 1, "0.3-0.5": 2, ">0.5": 2},
                "mean": 0.52,
                "count": 5,
            },
            message=None,
        )
        data = resp.model_dump()
        assert data["total_audits"] == 5
        assert data["latest_timestamp"] == "2026-01-01T00:00:00+00:00"
        assert data["local_factor_distribution"]["mean"] == 0.52

    def test_fairness_summary_empty(self):
        from app.models.response import FairnessSummaryResponse

        resp = FairnessSummaryResponse(
            total_audits=0,
            latest_timestamp=None,
            local_factor_distribution=None,
            message="No fairness audits recorded yet",
        )
        data = resp.model_dump()
        assert data["total_audits"] == 0
        assert data["message"] == "No fairness audits recorded yet"
