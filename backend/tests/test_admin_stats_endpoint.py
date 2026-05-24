"""Tests for GET /admin/stats endpoint — corpus operational visibility."""

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
from app.models.response import AdminStatsResponse


# ---------------------------------------------------------------------------
# Test app setup
# ---------------------------------------------------------------------------

def _build_app(retriever=None, bm25_vectorizer=None, hybrid_retriever=None, qdrant_service=None):
    """Build a minimal FastAPI with admin router and configurable state."""
    app = FastAPI()
    app.include_router(admin_router)
    app.state.retriever = retriever
    app.state.bm25_vectorizer = bm25_vectorizer
    app.state.hybrid_retriever = hybrid_retriever
    app.state.qdrant_service = qdrant_service

    mock_user = MagicMock()
    mock_user.id = "test-admin-user"
    mock_user.is_active = True
    mock_user_service = MagicMock()
    mock_user_service.get_by_id = AsyncMock(return_value=mock_user)
    app.state.user_service = mock_user_service

    return app


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer fake-jwt-token-for-tests"}


@pytest.fixture
def mock_decode_token():
    """Mock JWT decode to accept any fake token."""
    with patch("app.middleware.auth.decode_access_token") as mock:
        mock.return_value = {"sub": "test-admin-user"}
        yield mock


# ---------------------------------------------------------------------------
# GET /admin/stats — response shape and data
# ---------------------------------------------------------------------------

class TestAdminStatsEndpoint:
    """Verify GET /admin/stats returns proper corpus stats."""

    def test_returns_200_with_valid_jwt(self, auth_headers, mock_decode_token):
        """With valid JWT, stats endpoint returns 200."""
        client = TestClient(_build_app())
        response = client.get("/admin/stats", headers=auth_headers)
        assert response.status_code == 200

    def test_returns_empty_stats_when_no_components(self, auth_headers, mock_decode_token):
        """When app.state has no retriever/bm25/qdrant, return safe defaults."""
        client = TestClient(_build_app())
        response = client.get("/admin/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total_chunks"] == 0
        assert data["total_docs"] == 0
        assert data["language_distribution"] == {}
        assert data["bm25_vocab_size"] == 0
        assert data["hybrid_enabled"] is False
        assert data["qdrant_collection_name"] is None

    def test_returns_retriever_stats(self, auth_headers, mock_decode_token):
        """When retriever is present, return chunk/doc counts and language dist."""
        # Build mock chunks
        mock_chunk_vi = MagicMock()
        mock_chunk_vi.source_id = "doc-1"
        mock_chunk_vi.language = "vi"
        mock_chunk_vi.text = "Xin chào"

        mock_chunk_en = MagicMock()
        mock_chunk_en.source_id = "doc-2"
        mock_chunk_en.language = "en"
        mock_chunk_en.text = "Hello"

        mock_chunk_vi2 = MagicMock()
        mock_chunk_vi2.source_id = "doc-1"
        mock_chunk_vi2.language = "vi"
        mock_chunk_vi2.text = "Tái diễn"

        mock_retriever = MagicMock()
        mock_retriever.chunks = [mock_chunk_vi, mock_chunk_en, mock_chunk_vi2]

        client = TestClient(_build_app(retriever=mock_retriever))
        response = client.get("/admin/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total_chunks"] == 3
        assert data["total_docs"] == 2
        assert data["language_distribution"] == {"vi": 2, "en": 1}

    def test_returns_bm25_vocab_size(self, auth_headers, mock_decode_token):
        """When BM25 vectorizer is present, return vocab_size."""
        mock_bm25 = MagicMock()
        mock_bm25.vocab_size = 1523

        client = TestClient(_build_app(bm25_vectorizer=mock_bm25))
        response = client.get("/admin/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["bm25_vocab_size"] == 1523

    def test_returns_hybrid_enabled_true(self, auth_headers, mock_decode_token):
        """When hybrid_retriever is present, hybrid_enabled is true."""
        mock_hybrid = MagicMock()

        client = TestClient(_build_app(hybrid_retriever=mock_hybrid))
        response = client.get("/admin/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["hybrid_enabled"] is True

    def test_returns_qdrant_collection_name(self, auth_headers, mock_decode_token):
        """When qdrant_service is present, return collection_name."""
        mock_qdrant = MagicMock()
        mock_qdrant.collection_name = "ham-ninh-hybrid"

        client = TestClient(_build_app(qdrant_service=mock_qdrant))
        response = client.get("/admin/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["qdrant_collection_name"] == "ham-ninh-hybrid"

    def test_full_stats_with_all_components(self, auth_headers, mock_decode_token):
        """All components present — verify complete response shape."""
        mock_chunk = MagicMock()
        mock_chunk.source_id = "doc-a"
        mock_chunk.language = "vi"
        mock_retriever = MagicMock()
        mock_retriever.chunks = [mock_chunk]

        mock_bm25 = MagicMock()
        mock_bm25.vocab_size = 800

        mock_hybrid = MagicMock()
        mock_qdrant = MagicMock()
        mock_qdrant.collection_name = "test-collection"

        client = TestClient(_build_app(
            retriever=mock_retriever,
            bm25_vectorizer=mock_bm25,
            hybrid_retriever=mock_hybrid,
            qdrant_service=mock_qdrant,
        ))
        response = client.get("/admin/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total_chunks"] == 1
        assert data["total_docs"] == 1
        assert data["language_distribution"] == {"vi": 1}
        assert data["bm25_vocab_size"] == 800
        assert data["hybrid_enabled"] is True
        assert data["qdrant_collection_name"] == "test-collection"


# ---------------------------------------------------------------------------
# GET /admin/stats — auth enforcement
# ---------------------------------------------------------------------------

class TestAdminStatsAuth:
    """Verify JWT auth on GET /admin/stats."""

    def test_no_auth_returns_401(self):
        """Without Authorization header, /admin/stats returns 401."""
        client = TestClient(_build_app())
        response = client.get("/admin/stats", headers={})
        assert response.status_code == 401

    def test_invalid_token_returns_401(self):
        """With invalid token, /admin/stats returns 401."""
        client = TestClient(_build_app())
        response = client.get(
            "/admin/stats",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# AdminStatsResponse model
# ---------------------------------------------------------------------------

class TestAdminStatsResponseModel:
    """Verify AdminStatsResponse serializes correctly."""

    def test_full_response(self):
        resp = AdminStatsResponse(
            total_chunks=607,
            total_docs=64,
            language_distribution={"vi": 580, "en": 27},
            bm25_vocab_size=4521,
            hybrid_enabled=True,
            qdrant_collection_name="ham-ninh-hybrid",
        )
        data = resp.model_dump()
        assert data["total_chunks"] == 607
        assert data["total_docs"] == 64
        assert data["language_distribution"]["vi"] == 580
        assert data["bm25_vocab_size"] == 4521
        assert data["hybrid_enabled"] is True
        assert data["qdrant_collection_name"] == "ham-ninh-hybrid"

    def test_empty_defaults(self):
        resp = AdminStatsResponse(
            total_chunks=0,
            total_docs=0,
            language_distribution={},
            bm25_vocab_size=0,
            hybrid_enabled=False,
            qdrant_collection_name=None,
        )
        data = resp.model_dump()
        assert data["total_chunks"] == 0
        assert data["language_distribution"] == {}
        assert data["qdrant_collection_name"] is None
