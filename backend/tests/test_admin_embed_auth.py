"""Tests for POST /admin/embed JWT auth — verifies R011 (uniform JWT protection)."""

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

    # Mock app.state for bm25_vectorizer (required by admin router)
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
# POST /admin/embed — JWT auth tests
# ---------------------------------------------------------------------------

class TestAdminEmbedAuth:
    """Verify JWT auth on POST /admin/embed — was previously accessible in dev mode."""

    def test_no_auth_returns_401(self, client, no_auth_headers):
        """Without Authorization header, /admin/embed must return 401."""
        response = client.post(
            "/admin/embed",
            headers=no_auth_headers,
        )
        assert response.status_code == 401

    def test_invalid_token_returns_401(self, client):
        """With an invalid JWT, /admin/embed must return 401."""
        response = client.post(
            "/admin/embed",
            headers={"Authorization": "Bearer invalid-token-here"},
        )
        assert response.status_code == 401

    def test_valid_jwt_passes_auth_check(self, client, auth_headers, mock_decode_token):
        """With a valid JWT, /admin/embed passes auth and proceeds to embed logic."""
        with patch("app.routers.admin.load_proposition_corpus") as mock_load:
            mock_load.return_value = []  # Empty corpus → 500, but auth passed

            response = client.post(
                "/admin/embed",
                headers=auth_headers,
            )
            # Auth passed (not 401); 500 is expected because corpus is empty
            assert response.status_code != 401

    def test_malformed_auth_header_returns_401(self, client):
        """Malformed Authorization header (no 'Bearer ' prefix) returns 401."""
        response = client.post(
            "/admin/embed",
            headers={"Authorization": "InvalidFormat token"},
        )
        assert response.status_code == 401

    def test_expired_token_returns_401(self, client):
        """Token that decodes to None (expired) returns 401."""
        with patch("app.middleware.auth.decode_access_token", return_value=None):
            response = client.post(
                "/admin/embed",
                headers={"Authorization": "Bearer expired-token"},
            )
            assert response.status_code == 401
