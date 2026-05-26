"""Tests for admin eval endpoints — POST /admin/eval/trigger, GET /admin/eval/results, GET /admin/traces."""

import json
import os
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

def _build_app():
    """Build a minimal FastAPI with admin router for testing."""
    app = FastAPI()
    app.include_router(admin_router)

    # Mock app.state for bm25_vectorizer
    app.state.bm25_vectorizer = None

    # Mock user_service
    mock_user = MagicMock()
    mock_user.id = "test-admin-user"
    mock_user.is_active = True
    mock_user_service = AsyncMock()
    mock_user_service.get_by_id = AsyncMock(return_value=mock_user)
    app.state.user_service = mock_user_service

    return app


@pytest.fixture
def client():
    """TestClient with admin router."""
    app = _build_app()
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Headers with valid JWT Bearer token."""
    return {"Authorization": "Bearer fake-jwt-token-for-tests"}


@pytest.fixture
def no_auth_headers():
    """Headers without auth."""
    return {}


@pytest.fixture
def mock_decode_token():
    """Mock JWT decode to accept any fake token."""
    with patch("app.middleware.auth.decode_access_token") as mock:
        mock.return_value = {"sub": "test-admin-user"}
        yield mock


# ---------------------------------------------------------------------------
# POST /admin/eval/trigger — auth tests
# ---------------------------------------------------------------------------

class TestEvalTriggerAuth:
    """Verify JWT auth on POST /admin/eval/trigger."""

    def test_no_auth_returns_401(self, client, no_auth_headers):
        response = client.post(
            "/admin/eval/trigger",
            json={},
            headers=no_auth_headers,
        )
        assert response.status_code == 401

    def test_invalid_token_returns_401(self, client):
        response = client.post(
            "/admin/eval/trigger",
            json={},
            headers={"Authorization": "Bearer invalid-token-here"},
        )
        # Token decode fails → 401
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /admin/eval/trigger — credential-blocked tests
# ---------------------------------------------------------------------------

class TestEvalTriggerCredentialBlocked:
    """Verify credential_blocked behavior when no OPENAI_API_KEY."""

    def test_returns_credential_blocked_without_api_key(
        self, client, auth_headers, mock_decode_token
    ):
        """When OPENAI_API_KEY is not set, should return credential_blocked."""
        original_key = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with patch(
                "agents.ml.ragas_evaluator.RAGASEvaluator"
            ) as MockEvaluator:
                mock_eval = MagicMock()
                mock_eval.evaluate.return_value = {
                    "verdict": "credential_blocked",
                    "metrics": {},
                    "reason": "OPENAI_API_KEY not set",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "dataset_size": 0,
                    "latency_seconds": 0,
                }
                MockEvaluator.return_value = mock_eval

                response = client.post(
                    "/admin/eval/trigger",
                    json={},
                    headers=auth_headers,
                )
                assert response.status_code == 200
                data = response.json()
                assert data["verdict"] == "credential_blocked"
                assert data["metrics"] == {}
                assert "timestamp" in data
        finally:
            if original_key:
                os.environ["OPENAI_API_KEY"] = original_key

    def test_returns_credential_blocked_with_real_evaluator(
        self, client, auth_headers, mock_decode_token
    ):
        """Integration test: real RAGASEvaluator without API key returns blocked."""
        original_key = os.environ.pop("OPENAI_API_KEY", None)
        try:
            response = client.post(
                "/admin/eval/trigger",
                json={
                    "dataset_path": str(
                        _PROJECT_ROOT / "data" / "eval_dataset.jsonl"
                    )
                },
                headers=auth_headers,
            )
            assert response.status_code == 200
            data = response.json()
            assert data["verdict"] == "credential_blocked"
        finally:
            if original_key:
                os.environ["OPENAI_API_KEY"] = original_key


# ---------------------------------------------------------------------------
# GET /admin/traces — real status tests (S04 implementation)
# ---------------------------------------------------------------------------

class TestAdminTraces:
    """Verify GET /admin/traces returns real Langfuse status."""

    def test_returns_langfuse_status(
        self, client, auth_headers, mock_decode_token
    ):
        """Response should include langfuse_enabled and message."""
        with patch("app.routers.admin.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                LANGFUSE_HOST="http://langfuse:3000"
            )
            response = client.get("/admin/traces", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert "langfuse_enabled" in data
            assert "message" in data
            assert "Langfuse" in data["message"]

    def test_requires_auth(self, client, no_auth_headers):
        response = client.get("/admin/traces", headers=no_auth_headers)
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /admin/eval/results — listing tests
# ---------------------------------------------------------------------------

class TestEvalResultsListing:
    """Verify GET /admin/eval/results endpoint."""

    def test_requires_auth(self, client, no_auth_headers):
        response = client.get("/admin/eval/results", headers=no_auth_headers)
        assert response.status_code == 401

    def test_returns_empty_list_when_no_results(
        self, client, auth_headers, mock_decode_token
    ):
        """If data/eval_results/ doesn't exist, return empty list."""
        with patch("app.routers.admin.Path") as MockPath:
            mock_dir = MagicMock()
            mock_dir.exists.return_value = False
            MockPath.return_value = mock_dir

            response = client.get(
                "/admin/eval/results", headers=auth_headers
            )
            assert response.status_code == 200
            data = response.json()
            assert data == []

    def test_returns_listings_when_results_exist(
        self, client, auth_headers, mock_decode_token, tmp_path
    ):
        """Should list result files from data/eval_results/."""
        # Create a fake result file
        results_dir = tmp_path / "eval_results"
        results_dir.mkdir()
        result_file = results_dir / "eval_20260101T000000Z.json"
        result_data = {
            "verdict": "credential_blocked",
            "timestamp": "2026-01-01T00:00:00Z",
            "dataset_size": 12,
            "metrics": {},
        }
        with open(result_file, "w") as fh:
            json.dump(result_data, fh)

        with patch("app.routers.admin.Path") as MockPath:
            mock_dir = MagicMock()
            mock_dir.exists.return_value = True
            mock_dir.glob.return_value = [result_file]
            MockPath.return_value = mock_dir

            response = client.get(
                "/admin/eval/results", headers=auth_headers
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["verdict"] == "credential_blocked"
            assert data[0]["dataset_size"] == 12


# ---------------------------------------------------------------------------
# Response model tests
# ---------------------------------------------------------------------------

class TestResponseModels:
    """Verify Pydantic response models serialize correctly."""

    def test_eval_trigger_request_defaults(self):
        from app.models.response import EvalTriggerRequest

        req = EvalTriggerRequest()
        assert req.dataset_path is None
        assert req.metrics is None

    def test_eval_trigger_request_with_values(self):
        from app.models.response import EvalTriggerRequest

        req = EvalTriggerRequest(
            dataset_path="custom/path.jsonl",
            metrics=["faithfulness"],
        )
        assert req.dataset_path == "custom/path.jsonl"
        assert req.metrics == ["faithfulness"]

    def test_eval_result_response_serialization(self):
        from app.models.response import EvalResultResponse

        resp = EvalResultResponse(
            verdict="credential_blocked",
            metrics={},
            timestamp="2026-01-01T00:00:00Z",
            dataset_size=12,
            latency_ms=0.5,
        )
        data = resp.model_dump()
        assert data["verdict"] == "credential_blocked"
        assert data["dataset_size"] == 12

    def test_eval_file_listing_serialization(self):
        from app.models.response import EvalFileListing

        listing = EvalFileListing(
            filename="eval_20260101T000000Z.json",
            timestamp="2026-01-01T00:00:00Z",
            verdict="completed",
            dataset_size=12,
        )
        data = listing.model_dump()
        assert data["filename"] == "eval_20260101T000000Z.json"
        assert data["verdict"] == "completed"
