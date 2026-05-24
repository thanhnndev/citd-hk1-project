"""Tests verifying JWT auth on POST /admin/embed (R011 compliance).

The /admin/embed endpoint previously relied on router-level verify_api_key
(lenient dev-mode bypass). After this change it uses get_current_user(strict
JWT) like all other admin endpoints. These tests confirm the 401 behavior.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Resolve project root so we can import app.* regardless of cwd.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "backend"))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.admin import router as admin_router


# ---------------------------------------------------------------------------
# Test app setup — mirrors test_admin_traces_endpoint.py pattern
# ---------------------------------------------------------------------------

def _build_app():
    """Build a minimal FastAPI with admin router for testing."""
    app = FastAPI()
    app.include_router(admin_router)
    app.state.bm25_vectorizer = None

    mock_user = MagicMock()
    mock_user.id = "test-admin-user"
    mock_user.is_active = True
    mock_user_service = MagicMock()
    mock_user_service.get_by_id = AsyncMock(return_value=mock_user)
    app.state.user_service = mock_user_service

    return app


@pytest.fixture
def client():
    return TestClient(_build_app())


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
# POST /admin/embed — JWT auth enforcement
# ---------------------------------------------------------------------------

class TestAdminEmbedAuth:
    """Verify POST /admin/embed requires strict JWT (no dev-mode bypass)."""

    def test_no_auth_returns_401(self, client, no_auth_headers):
        """Without Authorization header, /admin/embed must return 401."""
        response = client.post("/admin/embed", headers=no_auth_headers)
        assert response.status_code == 401
        data = response.json()
        assert "Authorization" in data["detail"]

    def test_invalid_token_returns_401(self, client):
        """With a token that fails decode, /admin/embed must return 401."""
        response = client.post(
            "/admin/embed",
            headers={"Authorization": "Bearer expired-or-fake-token"},
        )
        assert response.status_code == 401

    def test_valid_jwt_passes_auth_gate(self, client, auth_headers, mock_decode_token):
        """With a valid JWT, auth gate passes (request may fail later due to no Qdrant)."""
        # Mock the embed internals so we don't need real Qdrant/OpenAI
        with patch("app.routers.admin.load_proposition_corpus") as mock_load, \
             patch("app.routers.admin.EmbeddingService") as mock_embed_cls, \
             patch("app.routers.admin.QdrantService") as mock_qdrant_cls:
            # Simulate corpus load returning empty to avoid deep mocking
            mock_load.return_value = []

            response = client.post("/admin/embed", headers=auth_headers)
            # With empty corpus we expect 500 (not 401), proving auth passed
            assert response.status_code == 500
            assert "no chunks" in response.json()["detail"].lower()

    def test_malformed_bearer_returns_401(self, client):
        """Malformed Authorization header (not 'Bearer <token>') returns 401."""
        response = client.post(
            "/admin/embed",
            headers={"Authorization": "InvalidFormat token"},
        )
        assert response.status_code == 401
