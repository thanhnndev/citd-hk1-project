"""Unit and integration tests for EmbeddingService.

Unit tests (no network, no Qdrant) run with -m 'not integration'.
Integration tests require a live OpenAI key and Qdrant instance.
"""

import asyncio
import os
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure required env vars are present before any app import.
for _key in ("OPENAI_API_KEY", "GOOGLE_PLACES_API_KEY", "GOOGLE_ROUTES_API_KEY"):
    os.environ.setdefault(_key, "fake-test-key")

from app.services.embedding_service import EmbeddingService
from app.services.qdrant_service import COLLECTION_NAME, QdrantService
from app.models.rag import RAGChunk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_response(vectors: List[List[float]]) -> MagicMock:
    """Build a mock openai embeddings response with the given vectors."""
    response = MagicMock()
    response.data = [MagicMock(embedding=v) for v in vectors]
    return response


def _fake_vectors(n: int, dim: int = 1536) -> List[List[float]]:
    """Generate n distinct fake vectors of dimension dim."""
    return [[float(i) / (n * dim)] * dim for i in range(n)]


# ---------------------------------------------------------------------------
# Unit tests — batching logic
# ---------------------------------------------------------------------------

class TestEmbedBatching:
    """Verify that embed_texts batches correctly and preserves order."""

    @pytest.mark.asyncio
    async def test_embed_batching_single_batch(self):
        """Fewer than BATCH_SIZE texts → exactly one API call."""
        svc = EmbeddingService()
        texts = [f"text {i}" for i in range(10)]
        fake_vecs = _fake_vectors(10)

        with patch.object(
            svc._client.embeddings,
            "create",
            new_callable=AsyncMock,
            return_value=_make_fake_response(fake_vecs),
        ) as mock_create:
            result = await svc.embed_texts(texts)

        assert mock_create.call_count == 1
        assert len(result) == 10
        assert result == fake_vecs

    @pytest.mark.asyncio
    async def test_embed_batching_multiple_batches(self):
        """250 texts → 3 API calls (100 + 100 + 50), order preserved."""
        svc = EmbeddingService()
        total = 250
        texts = [f"text {i}" for i in range(total)]

        # Build per-batch fake vectors so we can verify order preservation.
        batch_vecs = [
            _fake_vectors(100, dim=4),   # batch 0: indices 0–99
            _fake_vectors(100, dim=4),   # batch 1: indices 100–199
            _fake_vectors(50, dim=4),    # batch 2: indices 200–249
        ]
        call_count = 0

        async def fake_create(input, model):  # noqa: A002
            nonlocal call_count
            resp = _make_fake_response(batch_vecs[call_count])
            call_count += 1
            return resp

        with patch.object(svc._client.embeddings, "create", side_effect=fake_create):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await svc.embed_texts(texts)

        assert call_count == 3
        assert len(result) == total
        # Courtesy sleep called between batches (not before first batch).
        assert mock_sleep.call_count == 2
        # Verify order: first 100 come from batch_vecs[0], etc.
        assert result[:100] == batch_vecs[0]
        assert result[100:200] == batch_vecs[1]
        assert result[200:] == batch_vecs[2]

    @pytest.mark.asyncio
    async def test_embed_batching_exact_boundary(self):
        """Exactly BATCH_SIZE texts → one API call, no sleep."""
        svc = EmbeddingService()
        texts = [f"text {i}" for i in range(EmbeddingService.BATCH_SIZE)]
        fake_vecs = _fake_vectors(EmbeddingService.BATCH_SIZE, dim=4)

        with patch.object(
            svc._client.embeddings,
            "create",
            new_callable=AsyncMock,
            return_value=_make_fake_response(fake_vecs),
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await svc.embed_texts(texts)

        assert len(result) == EmbeddingService.BATCH_SIZE
        assert mock_sleep.call_count == 0

    @pytest.mark.asyncio
    async def test_embed_query_returns_single_vector(self):
        """embed_query is a convenience wrapper returning one vector."""
        svc = EmbeddingService()
        fake_vec = [0.1] * 1536

        with patch.object(
            svc._client.embeddings,
            "create",
            new_callable=AsyncMock,
            return_value=_make_fake_response([fake_vec]),
        ):
            result = await svc.embed_query("Hàm Ninh hải sản")

        assert result == fake_vec
        assert isinstance(result, list)
        assert len(result) == 1536

    @pytest.mark.asyncio
    async def test_embed_batching_passes_correct_model(self):
        """API calls use the model from settings."""
        svc = EmbeddingService()
        fake_vecs = _fake_vectors(2, dim=4)

        with patch.object(
            svc._client.embeddings,
            "create",
            new_callable=AsyncMock,
            return_value=_make_fake_response(fake_vecs),
        ) as mock_create:
            await svc.embed_texts(["a", "b"])

        _, kwargs = mock_create.call_args
        assert kwargs.get("model") == svc.model


# ---------------------------------------------------------------------------
# Unit tests — QdrantService upsert
# ---------------------------------------------------------------------------

def _make_chunk(idx: int) -> RAGChunk:
    """Build a minimal RAGChunk for testing."""
    return RAGChunk(
        chunk_id=f"chunk-{idx}",
        source_id=f"src-{idx}",
        title=f"Title {idx}",
        url=None,
        domain="tourism",
        source_type="blog",
        reliability="medium",
        language="vi",
        location="Hàm Ninh",
        text=f"Some text for chunk {idx}",
        chunk_index=idx,
        total_chunks=10,
    )


class TestQdrantServiceUpsert:
    """Verify QdrantService.upsert_chunks returns correct point count."""

    @pytest.mark.asyncio
    async def test_upsert_point_count(self):
        """upsert_chunks returns the number of points passed in."""
        n = 5
        chunks = [_make_chunk(i) for i in range(n)]
        vectors = [[float(i)] * 1536 for i in range(n)]

        svc = QdrantService(url="http://localhost:6333")

        mock_upsert = AsyncMock()

        with patch.object(svc._client, "upsert", mock_upsert):
            count = await svc.upsert_chunks(chunks, vectors)

        assert count == n
        mock_upsert.assert_awaited_once()
        # Verify the call used the correct collection name
        call_kwargs = mock_upsert.call_args
        assert call_kwargs.kwargs.get("collection_name") == COLLECTION_NAME
        assert len(call_kwargs.kwargs.get("points", [])) == n

    @pytest.mark.asyncio
    async def test_upsert_payload_fields(self):
        """Each upserted point carries all RAGChunk fields in its payload."""
        chunk = _make_chunk(0)
        vector = [0.1] * 1536

        svc = QdrantService(url="http://localhost:6333")
        mock_upsert = AsyncMock()

        with patch.object(svc._client, "upsert", mock_upsert):
            await svc.upsert_chunks([chunk], [vector])

        points = mock_upsert.call_args.kwargs["points"]
        payload = points[0].payload

        assert payload["chunk_id"] == chunk.chunk_id
        assert payload["source_id"] == chunk.source_id
        assert payload["title"] == chunk.title
        assert payload["domain"] == chunk.domain
        assert payload["source_type"] == chunk.source_type
        assert payload["reliability"] == chunk.reliability
        assert payload["language"] == chunk.language
        assert payload["location"] == chunk.location
        assert payload["text"] == chunk.text
        assert payload["chunk_index"] == chunk.chunk_index
        assert payload["total_chunks"] == chunk.total_chunks

    @pytest.mark.asyncio
    async def test_upsert_point_ids_are_sequential(self):
        """Point IDs are assigned as 0..N-1."""
        n = 3
        chunks = [_make_chunk(i) for i in range(n)]
        vectors = [[0.0] * 1536 for _ in range(n)]

        svc = QdrantService(url="http://localhost:6333")
        mock_upsert = AsyncMock()

        with patch.object(svc._client, "upsert", mock_upsert):
            await svc.upsert_chunks(chunks, vectors)

        points = mock_upsert.call_args.kwargs["points"]
        assert [p.id for p in points] == list(range(n))


# ---------------------------------------------------------------------------
# Integration marker (skipped in unit runs)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestEmbeddingIntegration:
    """Live tests — require OPENAI_API_KEY and Qdrant at :46333."""

    @pytest.mark.asyncio
    async def test_embed_query_real_vector_shape(self):
        """Real API call returns a 1536-dim vector."""
        if not _is_real_api_key():
            pytest.skip("Skipping: OPENAI_API_KEY is fake")
        svc = EmbeddingService()
        vec = await svc.embed_query("làng chài Hàm Ninh")
        assert len(vec) == 1536
        assert all(isinstance(x, float) for x in vec)


# ---------------------------------------------------------------------------
# Integration tests — corpus indexing and semantic search
# ---------------------------------------------------------------------------

def _is_real_api_key() -> bool:
    """Return True when OPENAI_API_KEY looks like a real key."""
    key = os.environ.get("OPENAI_API_KEY", "")
    return bool(key) and not key.startswith("fake")


@pytest.mark.integration
class TestEmbeddingIndex:
    """Prove 321 chunks are indexed in Qdrant with correct vector shape."""

    @pytest.mark.asyncio
    async def test_collection_exists_after_embed(self):
        """POST /admin/embed returns 200 with total_chunks=321 and vector_dim=1536."""
        if not _is_real_api_key():
            pytest.skip("Skipping: OPENAI_API_KEY is fake")

        import httpx
        from app.main import app

        qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:46333")
        api_key = os.environ.get("BACKEND_API_KEY", "test-admin-key")

        async with httpx.AsyncClient(
            app=app,
            base_url="http://test",
            headers={"X-API-Key": api_key},
        ) as client:
            resp = await client.post("/admin/embed")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_chunks"] == 321
        assert body["vector_dim"] == 1536
        assert body["collection_name"] == COLLECTION_NAME

    @pytest.mark.asyncio
    async def test_all_chunks_indexed(self):
        """QdrantService.collection_info() reports points_count == 321."""
        if not _is_real_api_key():
            pytest.skip("Skipping: OPENAI_API_KEY is fake")

        qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:46333")
        svc = QdrantService(url=qdrant_url)
        info = await svc.collection_info()
        assert info["points_count"] == 321

    @pytest.mark.asyncio
    async def test_vector_dimension(self):
        """Search result vectors are 1536-dimensional."""
        if not _is_real_api_key():
            pytest.skip("Skipping: OPENAI_API_KEY is fake")

        qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:46333")
        svc = QdrantService(url=qdrant_url)
        results = await svc.search(query_vector=[0.0] * 1536, top_k=1)
        assert len(results) >= 1
        assert len(results[0].vector) == 1536


@pytest.mark.integration
class TestSemanticSearch:
    """Prove semantic search returns relevant Hàm Ninh results."""

    @pytest.mark.asyncio
    async def test_ham_ninh_query_returns_relevant_chunks(self):
        """'làng chài Hàm Ninh' query returns ≥3 results mentioning Hàm Ninh."""
        if not _is_real_api_key():
            pytest.skip("Skipping: OPENAI_API_KEY is fake")

        qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:46333")
        embed_svc = EmbeddingService()
        qdrant_svc = QdrantService(url=qdrant_url)

        query_vec = await embed_svc.embed_query("làng chài Hàm Ninh")
        results = await qdrant_svc.search(query_vec, top_k=5)

        assert len(results) >= 3
        relevant = [
            r for r in results
            if "hàm ninh" in (r.payload.get("title", "") + r.payload.get("text", "")).lower()
            or "ham ninh" in (r.payload.get("title", "") + r.payload.get("text", "")).lower()
        ]
        assert len(relevant) >= 3, (
            f"Expected ≥3 Hàm Ninh results, got {len(relevant)}. "
            f"Titles: {[r.payload.get('title') for r in results]}"
        )

    @pytest.mark.asyncio
    async def test_seafood_query(self):
        """'hải sản Phú Quốc' top result has location containing Phú Quốc."""
        if not _is_real_api_key():
            pytest.skip("Skipping: OPENAI_API_KEY is fake")

        qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:46333")
        embed_svc = EmbeddingService()
        qdrant_svc = QdrantService(url=qdrant_url)

        query_vec = await embed_svc.embed_query("hải sản Phú Quốc")
        results = await qdrant_svc.search(query_vec, top_k=5)

        assert len(results) >= 1
        top_location = results[0].payload.get("location", "")
        assert "phú quốc" in top_location.lower() or "phu quoc" in top_location.lower(), (
            f"Expected top result location to contain Phú Quốc, got: {top_location!r}"
        )

    @pytest.mark.asyncio
    async def test_search_returns_five_results(self):
        """Generic tourism query returns exactly top_k=5 results."""
        if not _is_real_api_key():
            pytest.skip("Skipping: OPENAI_API_KEY is fake")

        qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:46333")
        embed_svc = EmbeddingService()
        qdrant_svc = QdrantService(url=qdrant_url)

        query_vec = await embed_svc.embed_query("du lịch Phú Quốc")
        results = await qdrant_svc.search(query_vec, top_k=5)
        assert len(results) == 5
