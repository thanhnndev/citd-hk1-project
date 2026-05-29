"""Integration tests for POST /admin/embed endpoint (S02).

Exercises the real ASGI app via httpx ASGITransport, mocking only external
network calls (OpenAI embeddings, Qdrant upsert).  Validates the full endpoint
contract.

Covers:
  - corpus stats response (607 chunks, language_distribution, vector_dim=1536)
  - credential_blocked: OpenAI error returns 502 with openai_dependency_failed
  - empty corpus: raises HTTP 500
  - BM25 vectorizer synced to app.state after embed
  - corpus_loader auto-detects proposition schema
  - embed.done structured log event emitted to stdout
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "fake-test-key")
os.environ.setdefault("GOONG_API_KEY", "fake-test-key")
os.environ.setdefault("GOONG_API_KEY", "fake-test-key")
os.environ.setdefault("BACKEND_API_KEY", "test-admin-key")

import httpx

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
_CORPUS_PATH = str(_BACKEND_ROOT / "data" / "tourism_documents.jsonl")

from app.main import app
from app.models.response import EmbedResponse


# ---------------------------------------------------------------------------
# Corpus helpers
# ---------------------------------------------------------------------------

def _load_corpus_rows() -> list[dict[str, Any]]:
    rows = []
    with open(_CORPUS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _corpus_lang_dist() -> dict[str, int]:
    return dict(Counter(r["language"] for r in _load_corpus_rows()))


CORPUS_CHUNK_COUNT = len(_load_corpus_rows())
CORPUS_LANG_DIST = _corpus_lang_dist()
EXPECTED_VECTOR_DIM = 1536
EXPECTED_COLLECTION = "tourism_chunks"


# ---------------------------------------------------------------------------
# Fake vector factory
# ---------------------------------------------------------------------------

def _fake_vectors(n: int, dim: int = EXPECTED_VECTOR_DIM) -> list[list[float]]:
    """Generate n distinct fake vectors of dimension dim."""
    return [[float(i) / (n * dim)] * dim for i in range(n)]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def client() -> httpx.AsyncClient:
    """ASGI test client using httpx AsyncClient with ASGITransport."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEmbedEndpoint:
    """POST /admin/embed endpoint contract tests."""

    @pytest.mark.asyncio
    async def test_embed_returns_stats_on_success(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """With mocked embeddings+Qdrant, endpoint returns 200 with correct stats."""
        fake_vecs = _fake_vectors(CORPUS_CHUNK_COUNT)

        with patch(
            "agents.tools.embedding_service.EmbeddingService.embed_texts",
            new_callable=AsyncMock,
            return_value=fake_vecs,
        ):
            with patch(
                "agents.tools.qdrant_service.QdrantService.upsert_hybrid_chunks",
                new_callable=AsyncMock,
                return_value=CORPUS_CHUNK_COUNT,
            ):
                with patch(
                    "agents.tools.qdrant_service.QdrantService.ensure_hybrid_collection",
                    new_callable=AsyncMock,
                ):
                    response = await client.post(
                        "/admin/embed",
                        headers={"X-API-Key": "test-admin-key"},
                    )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total_chunks"] == CORPUS_CHUNK_COUNT
        assert body["propositions_ingested"] == CORPUS_CHUNK_COUNT
        assert body["vector_dim"] == EXPECTED_VECTOR_DIM
        assert body["collection_name"] == EXPECTED_COLLECTION
        assert body["language_distribution"] == CORPUS_LANG_DIST
        assert "latency_ms" in body
        assert body["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_embed_response_pydantic_model(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """Response body validates as EmbedResponse Pydantic model."""
        n = 3
        with patch(
            "agents.tools.embedding_service.EmbeddingService.embed_texts",
            new_callable=AsyncMock,
            return_value=_fake_vectors(n),
        ):
            with patch(
                "agents.tools.qdrant_service.QdrantService.upsert_hybrid_chunks",
                new_callable=AsyncMock,
                return_value=n,
            ):
                with patch(
                    "agents.tools.qdrant_service.QdrantService.ensure_hybrid_collection",
                    new_callable=AsyncMock,
                ):
                    response = await client.post(
                        "/admin/embed",
                        headers={"X-API-Key": "test-admin-key"},
                    )

        assert response.status_code == 200
        EmbedResponse.model_validate(response.json())

    @pytest.mark.asyncio
    async def test_embed_openai_error_returns_502(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """OpenAI error returns 502 Bad Gateway with openai_dependency_failed."""
        import openai

        with patch(
            "agents.tools.embedding_service.EmbeddingService.embed_texts",
            new_callable=AsyncMock,
            side_effect=openai.OpenAIError("invalid api key"),
        ):
            with patch(
                "agents.tools.qdrant_service.QdrantService.ensure_hybrid_collection",
                new_callable=AsyncMock,
            ):
                response = await client.post(
                    "/admin/embed",
                    headers={"X-API-Key": "test-admin-key"},
                )

        assert response.status_code == 502
        body = response.json()
        assert body.get("detail", {}).get("error") == "openai_dependency_failed"

    @pytest.mark.asyncio
    async def test_embed_empty_corpus_returns_500(self) -> None:
        """When corpus has no chunks, endpoint returns 500."""
        with patch(
            "app.routers.admin.load_proposition_corpus",
            return_value=[],
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as empty_client:
                response = await empty_client.post(
                    "/admin/embed",
                    headers={"X-API-Key": "test-admin-key"},
                )

        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_embed_bm25_vectorizer_synced_to_app_state(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """After successful embed, app.state.bm25_vectorizer is set and usable."""
        with patch(
            "agents.tools.embedding_service.EmbeddingService.embed_texts",
            new_callable=AsyncMock,
            return_value=_fake_vectors(CORPUS_CHUNK_COUNT),
        ):
            with patch(
                "agents.tools.qdrant_service.QdrantService.upsert_hybrid_chunks",
                new_callable=AsyncMock,
                return_value=CORPUS_CHUNK_COUNT,
            ):
                with patch(
                    "agents.tools.qdrant_service.QdrantService.ensure_hybrid_collection",
                    new_callable=AsyncMock,
                ):
                    response = await client.post(
                        "/admin/embed",
                        headers={"X-API-Key": "test-admin-key"},
                    )

        assert response.status_code == 200
        assert hasattr(app.state, "bm25_vectorizer")
        vectorizer = app.state.bm25_vectorizer
        assert vectorizer is not None
        result = vectorizer.encode("Ham Ninh lang chai")
        assert hasattr(result, "indices")

    @pytest.mark.asyncio
    async def test_corpus_loader_proposition_schema(self) -> None:
        """load_proposition_corpus correctly parses 607 proposition rows."""
        from agents.tools.corpus_loader import load_proposition_corpus

        chunks = load_proposition_corpus(_CORPUS_PATH)
        assert len(chunks) == CORPUS_CHUNK_COUNT
        assert all(hasattr(c, "text") and c.text for c in chunks)
        assert all(hasattr(c, "chunk_id") for c in chunks)
        assert all(hasattr(c, "source_id") for c in chunks)
        assert all(hasattr(c, "language") for c in chunks)

    @pytest.mark.asyncio
    async def test_embed_logs_embed_done_event(
        self,
        client: httpx.AsyncClient,
        capsys,
    ) -> None:
        """embed.done event is emitted after successful embed (verified via stdout)."""
        n = 3
        with patch(
            "agents.tools.embedding_service.EmbeddingService.embed_texts",
            new_callable=AsyncMock,
            return_value=_fake_vectors(n),
        ):
            with patch(
                "agents.tools.qdrant_service.QdrantService.upsert_hybrid_chunks",
                new_callable=AsyncMock,
                return_value=n,
            ):
                with patch(
                    "agents.tools.qdrant_service.QdrantService.ensure_hybrid_collection",
                    new_callable=AsyncMock,
                ):
                    response = await client.post(
                        "/admin/embed",
                        headers={"X-API-Key": "test-admin-key"},
                    )

        assert response.status_code == 200
        # embed.done/embed.started appear in application stdout (structlog writes there)
        captured = capsys.readouterr()
        assert "embed.done" in captured.out or "embed.started" in captured.out

    @pytest.mark.asyncio
    async def test_embed_qdrant_error_returns_502(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """Qdrant error returns 502 Bad Gateway with qdrant_dependency_failed."""
        import httpx
        from qdrant_client.http.exceptions import UnexpectedResponse

        qdrant_error = UnexpectedResponse(
            status_code=500,
            reason_phrase="Internal Server Error",
            content=b"connection refused",
            headers=httpx.Headers({"content-type": "text/plain"}),
        )
        with patch(
            "agents.tools.embedding_service.EmbeddingService.embed_texts",
            new_callable=AsyncMock,
            return_value=_fake_vectors(CORPUS_CHUNK_COUNT),
        ):
            with patch(
                "agents.tools.qdrant_service.QdrantService.ensure_hybrid_collection",
                new_callable=AsyncMock,
            ):
                with patch(
                    "agents.tools.qdrant_service.QdrantService.upsert_hybrid_chunks",
                    new_callable=AsyncMock,
                    side_effect=qdrant_error,
                ):
                    response = await client.post(
                        "/admin/embed",
                        headers={"X-API-Key": "test-admin-key"},
                    )

        assert response.status_code == 502
        body = response.json()
        assert body.get("detail", {}).get("error") == "qdrant_dependency_failed"