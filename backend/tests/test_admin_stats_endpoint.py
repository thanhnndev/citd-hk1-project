"""Tests for GET /admin/stats endpoint — JWT auth and corpus stats shape."""

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

def _build_app(retriever=None, bm25_vectorizer=None, hybrid_retriever=None, qdrant_service=None):
    """Build a minimal FastAPI with admin router for testing."""
    app = FastAPI()
    app.include_router(admin_router)

    app.state.bm25_vectorizer = bm25_vectorizer
    app.state.retriever = retriever
    app.state.hybrid_retriever = hybrid_retriever
    app.state.qdrant_service = qdrant_service

    # Mock user_service
    mock_user = MagicMock()
    mock_user.id = "test-admin-user"
    mock_user.is_active = True
    mock_user_service = AsyncMock()
    mock_user_service.get_by_id = AsyncMock(return_value=mock_user)
    app.state.user_service = mock_user_service

    return app


@pytest.fixture
def client_no_components():
    """TestClient with no retriever/bm25/hybrid/qdrant initialized."""
    return TestClient(_build_app())


@pytest.fixture
def client_with_retriever():
    """TestClient with a mock retriever containing sample chunks."""
    # Build mock chunks
    mock_chunk_vi = MagicMock()
    mock_chunk_vi.source_id = "doc-001"
    mock_chunk_vi.language = "vi"

    mock_chunk_en = MagicMock()
    mock_chunk_en.source_id = "doc-002"
    mock_chunk_en.language = "en"

    mock_chunk_vi2 = MagicMock()
    mock_chunk_vi2.source_id = "doc-001"
    mock_chunk_vi2.language = "vi"

    mock_retriever = MagicMock()
    mock_retriever.chunks = [mock_chunk_vi, mock_chunk_en, mock_chunk_vi2]

    # BM25 vectorizer with vocab
    mock_bm25 = MagicMock()
    mock_bm25.vocab_size = 42

    # Hybrid retriever present
    mock_hybrid = MagicMock()

    # Qdrant service
    mock_qdrant = MagicMock()
    mock_qdrant.collection_name = "tourism-hybrid"

    return TestClient(_build_app(
        retriever=mock_retriever,
        bm25_vectorizer=mock_bm25,
        hybrid_retriever=mock_hybrid,
        qdrant_service=mock_qdrant,
    ))


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
# GET /admin/stats — JWT auth tests
# ---------------------------------------------------------------------------

class TestAdminStatsAuth:
    """Verify JWT auth on GET /admin/stats."""

    def test_no_auth_returns_401(self, client_no_components, no_auth_headers):
        """Without Authorization header, /admin/stats must return 401."""
        response = client_no_components.get("/admin/stats", headers=no_auth_headers)
        assert response.status_code == 401

    def test_invalid_token_returns_401(self, client_no_components):
        """With an invalid JWT, /admin/stats must return 401."""
        response = client_no_components.get(
            "/admin/stats",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code == 401

    def test_valid_jwt_passes_auth(self, client_no_components, auth_headers, mock_decode_token):
        """With a valid JWT, /admin/stats passes auth and returns 200."""
        response = client_no_components.get("/admin/stats", headers=auth_headers)
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /admin/stats — response shape tests
# ---------------------------------------------------------------------------

class TestAdminStatsResponse:
    """Verify GET /admin/stats returns proper corpus stats shape."""

    def test_returns_defaults_when_no_components(
        self, client_no_components, auth_headers, mock_decode_token
    ):
        """When no retriever/bm25/hybrid is initialized, return safe defaults."""
        response = client_no_components.get("/admin/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        assert data["total_chunks"] == 0
        assert data["total_docs"] == 0
        assert data["language_distribution"] == {}
        assert data["bm25_vocab_size"] == 0
        assert data["hybrid_enabled"] is False
        assert data["qdrant_collection_name"] is None

    def test_returns_stats_with_retriever(
        self, client_with_retriever, auth_headers, mock_decode_token
    ):
        """When retriever has chunks, return accurate stats."""
        response = client_with_retriever.get("/admin/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        # 3 chunks: 2 from doc-001 (vi), 1 from doc-002 (en)
        assert data["total_chunks"] == 3
        assert data["total_docs"] == 2  # doc-001 and doc-002
        assert data["language_distribution"] == {"vi": 2, "en": 1}
        assert data["bm25_vocab_size"] == 42
        assert data["hybrid_enabled"] is True
        assert data["qdrant_collection_name"] == "tourism-hybrid"

    def test_returns_stats_without_hybrid(
        self, auth_headers, mock_decode_token
    ):
        """When hybrid retriever is None, hybrid_enabled should be false."""
        mock_chunk = MagicMock()
        mock_chunk.source_id = "doc-001"
        mock_chunk.language = "vi"

        mock_retriever = MagicMock()
        mock_retriever.chunks = [mock_chunk]

        mock_bm25 = MagicMock()
        mock_bm25.vocab_size = 10

        app = _build_app(
            retriever=mock_retriever,
            bm25_vectorizer=mock_bm25,
            hybrid_retriever=None,
            qdrant_service=None,
        )
        client = TestClient(app)

        response = client.get("/admin/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        assert data["total_chunks"] == 1
        assert data["total_docs"] == 1
        assert data["language_distribution"] == {"vi": 1}
        assert data["bm25_vocab_size"] == 10
        assert data["hybrid_enabled"] is False
        assert data["qdrant_collection_name"] is None

    def test_response_model_fields_match_schema(
        self, client_with_retriever, auth_headers, mock_decode_token
    ):
        """All required AdminStatsResponse fields must be present."""
        response = client_with_retriever.get("/admin/stats", headers=auth_headers)
        data = response.json()

        required_fields = [
            "total_chunks", "total_docs", "language_distribution",
            "bm25_vocab_size", "hybrid_enabled", "qdrant_collection_name",
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Response model tests
# ---------------------------------------------------------------------------

class TestAdminStatsModel:
    """Verify AdminStatsResponse Pydantic model serializes correctly."""

    def test_stats_response_with_data(self):
        from app.models.response import AdminStatsResponse

        resp = AdminStatsResponse(
            total_chunks=150,
            total_docs=45,
            language_distribution={"vi": 100, "en": 50},
            bm25_vocab_size=2048,
            hybrid_enabled=True,
            qdrant_collection_name="tourism-hybrid",
        )
        data = resp.model_dump()
        assert data["total_chunks"] == 150
        assert data["total_docs"] == 45
        assert data["language_distribution"] == {"vi": 100, "en": 50}
        assert data["bm25_vocab_size"] == 2048
        assert data["hybrid_enabled"] is True
        assert data["qdrant_collection_name"] == "tourism-hybrid"

    def test_stats_response_defaults(self):
        from app.models.response import AdminStatsResponse

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
        assert data["hybrid_enabled"] is False
        assert data["qdrant_collection_name"] is None
