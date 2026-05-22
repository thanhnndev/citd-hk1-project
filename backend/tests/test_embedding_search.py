"""Unit and integration tests for EmbeddingService.

Unit tests (no network, no Qdrant) run with -m 'not integration'.
Integration tests require a live OpenAI key and Qdrant instance.
"""

import asyncio
import os
from typing import Any, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure required env vars are present before any app import.
for _key in ("OPENAI_API_KEY", "GOOGLE_PLACES_API_KEY", "GOOGLE_ROUTES_API_KEY"):
    os.environ.setdefault(_key, "fake-test-key")

from app.services.embedding_service import EmbeddingService, EmbeddingValidationError
from app.services.qdrant_service import (
    COLLECTION_NAME,
    DENSE_VECTOR_NAME,
    VECTOR_SIZE,
    QdrantService,
)
from app.models.rag import RAGChunk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_response(vectors: List[List[float]]) -> MagicMock:
    """Build a mock openai embeddings response with the given vectors."""
    response = MagicMock()
    response.data = [MagicMock(embedding=v) for v in vectors]
    return response


def _fake_vectors(n: int, dim: int = VECTOR_SIZE) -> List[List[float]]:
    """Generate n distinct fake vectors of dimension dim."""
    return [[float(i) / (n * dim)] * dim for i in range(n)]



EXPECTED_CORPUS_CHUNKS = 607

def _extract_dense_vector(vector: Any) -> list[float]:
    """Return the dense vector from either unnamed or named Qdrant results."""
    if isinstance(vector, dict):
        assert DENSE_VECTOR_NAME in vector, (
            f"Expected named vector {DENSE_VECTOR_NAME!r}; got keys {sorted(vector.keys())}"
        )
        vector = vector[DENSE_VECTOR_NAME]
    assert isinstance(vector, list), f"Expected dense vector list, got {type(vector).__name__}"
    return vector

def _assert_collection_info_indexed(info: dict) -> None:
    """Assert Qdrant reports the expected named dense-vector corpus state."""
    assert info["collection_name"] == COLLECTION_NAME
    assert info["points_count"] == EXPECTED_CORPUS_CHUNKS
    assert info["dense_vector_name"] == DENSE_VECTOR_NAME
    assert info["dense_vector_size"] == VECTOR_SIZE
    assert DENSE_VECTOR_NAME in info["named_vectors"], info

def _qdrant_url() -> str:
    return os.environ.get("QDRANT_URL", "http://localhost:46333")

def _skip_without_real_openai_key() -> None:
    if os.environ.get("RUN_LIVE_EMBEDDING_TESTS") != "1":
        pytest.skip("Skipping credentialed embedding integration: set RUN_LIVE_EMBEDDING_TESTS=1")
    if not _is_real_api_key():
        pytest.skip("Skipping credentialed embedding integration: OPENAI_API_KEY is missing or fake")

async def _post_admin_embed() -> dict:
    """Call /admin/embed through the configured backend URL or ASGI app."""
    import httpx

    api_key = os.environ.get("BACKEND_API_KEY", "test-admin-key")
    backend_url = os.environ.get("BACKEND_URL")
    headers = {"X-API-Key": api_key}

    if backend_url:
        async with httpx.AsyncClient(base_url=backend_url.rstrip("/"), headers=headers, timeout=300) as client:
            resp = await client.post("/admin/embed")
    else:
        from app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers=headers,
        ) as client:
            resp = await client.post("/admin/embed")

    assert resp.status_code == 200, f"/admin/embed failed: {resp.status_code} {resp.text}"
    body = resp.json()
    assert body["total_chunks"] == EXPECTED_CORPUS_CHUNKS, body
    assert body["vector_dim"] == VECTOR_SIZE, body
    assert body["collection_name"] == COLLECTION_NAME, body
    return body

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
            _fake_vectors(100),   # batch 0: indices 0–99
            _fake_vectors(100),   # batch 1: indices 100–199
            _fake_vectors(50),    # batch 2: indices 200–249
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
        fake_vecs = _fake_vectors(EmbeddingService.BATCH_SIZE)

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
        fake_vec = [0.1] * VECTOR_SIZE

        with patch.object(
            svc._client.embeddings,
            "create",
            new_callable=AsyncMock,
            return_value=_make_fake_response([fake_vec]),
        ):
            result = await svc.embed_query("Hàm Ninh hải sản")

        assert result == fake_vec
        assert isinstance(result, list)
        assert len(result) == VECTOR_SIZE


    @pytest.mark.asyncio
    async def test_embed_rejects_response_count_mismatch(self):
        """Provider responses must include one vector for each input text."""
        svc = EmbeddingService()

        with patch.object(
            svc._client.embeddings,
            "create",
            new_callable=AsyncMock,
            return_value=_make_fake_response(_fake_vectors(1)),
        ):
            with pytest.raises(EmbeddingValidationError, match="count mismatch"):
                await svc.embed_texts(["a", "b"])

    @pytest.mark.asyncio
    async def test_embed_rejects_wrong_vector_dimension(self):
        """Provider vectors must match the Qdrant dense vector contract."""
        svc = EmbeddingService()

        with patch.object(
            svc._client.embeddings,
            "create",
            new_callable=AsyncMock,
            return_value=_make_fake_response([[0.1] * (VECTOR_SIZE - 1)]),
        ):
            with pytest.raises(EmbeddingValidationError, match="dimension mismatch"):
                await svc.embed_texts(["a"])

    @pytest.mark.asyncio
    async def test_embed_batching_passes_correct_model(self):
        """API calls use the model from settings."""
        svc = EmbeddingService()
        fake_vecs = _fake_vectors(2)

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
        vectors = [[float(i)] * VECTOR_SIZE for i in range(n)]

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
        vector = [0.1] * VECTOR_SIZE

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
        vectors = [[0.0] * VECTOR_SIZE for _ in range(n)]

        svc = QdrantService(url="http://localhost:6333")
        mock_upsert = AsyncMock()

        with patch.object(svc._client, "upsert", mock_upsert):
            await svc.upsert_chunks(chunks, vectors)

        points = mock_upsert.call_args.kwargs["points"]
        assert [p.id for p in points] == list(range(n))



    @pytest.mark.asyncio
    async def test_collection_info_exposes_named_dense_vector_config(self):
        """collection_info exposes counts and named dense vector size only."""
        svc = QdrantService(url="http://localhost:6333")

        dense_cfg = MagicMock()
        dense_cfg.size = VECTOR_SIZE
        dense_cfg.distance = "Cosine"
        params = MagicMock()
        params.vectors = {DENSE_VECTOR_NAME: dense_cfg}
        params.sparse_vectors = {"sparse": MagicMock()}
        config = MagicMock()
        config.params = params
        info = MagicMock()
        info.config = config
        info.points_count = 607
        info.vectors_count = 607

        with patch.object(svc._client, "get_collection", AsyncMock(return_value=info)):
            result = await svc.collection_info()

        assert result["collection_name"] == COLLECTION_NAME
        assert result["points_count"] == 607
        assert result["vectors_count"] == 607
        assert result["dense_vector_name"] == DENSE_VECTOR_NAME
        assert result["dense_vector_size"] == VECTOR_SIZE
        assert result["named_vectors"] == [DENSE_VECTOR_NAME]


class TestNamedVectorHelpers:
    """Guard integration assertions against silent named-vector regressions."""

    def test_extract_dense_vector_from_named_result(self):
        dense = [0.1] * VECTOR_SIZE
        assert _extract_dense_vector({DENSE_VECTOR_NAME: dense}) == dense

    def test_extract_dense_vector_rejects_missing_dense_key(self):
        with pytest.raises(AssertionError, match="Expected named vector"):
            _extract_dense_vector({"other": [0.1]})

    def test_collection_info_asserts_named_dense_shape(self):
        _assert_collection_info_indexed({
            "collection_name": COLLECTION_NAME,
            "points_count": EXPECTED_CORPUS_CHUNKS,
            "dense_vector_name": DENSE_VECTOR_NAME,
            "dense_vector_size": VECTOR_SIZE,
            "named_vectors": [DENSE_VECTOR_NAME],
        })

    def test_collection_info_rejects_unnamed_schema(self):
        with pytest.raises(AssertionError):
            _assert_collection_info_indexed({
                "collection_name": COLLECTION_NAME,
                "points_count": EXPECTED_CORPUS_CHUNKS,
                "dense_vector_name": DENSE_VECTOR_NAME,
                "dense_vector_size": VECTOR_SIZE,
                "named_vectors": [],
            })


class TestEmbeddingVerifierReadiness:
    """Guard the external readiness diagnostic used before live embedding calls."""

    def test_openai_key_status_is_secret_safe(self):
        import importlib.util
        from pathlib import Path

        script = Path(__file__).resolve().parents[2] / "scripts" / "verify-embedding-idempotency.py"
        spec = importlib.util.spec_from_file_location("verify_embedding_idempotency", script)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-live-secret-value"}, clear=False):
            spec.loader.exec_module(module)
            assert module.key_status() == "present"

    def test_redacted_openai_key_is_credential_blocked(self):
        import importlib.util
        from pathlib import Path

        script = Path(__file__).resolve().parents[2] / "scripts" / "verify-embedding-idempotency.py"
        spec = importlib.util.spec_from_file_location("verify_embedding_idempotency_placeholder", script)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader

        with patch.dict(os.environ, {"OPENAI_API_KEY": "[REDACTED:openai]"}, clear=False):
            spec.loader.exec_module(module)
            assert module.key_status() == "placeholder"
            assert module.credential_blocked() is True

    def test_masked_openai_key_is_not_real_for_integration_gate(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-proj-abcdefghijklmnopxxxx"}, clear=False):
            assert _is_real_api_key() is False

    def test_fake_openai_key_is_credential_blocked(self):
        import importlib.util
        from pathlib import Path

        script = Path(__file__).resolve().parents[2] / "scripts" / "verify-embedding-idempotency.py"
        spec = importlib.util.spec_from_file_location("verify_embedding_idempotency_fake", script)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader

        with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-test-key"}, clear=False):
            spec.loader.exec_module(module)
            assert module.key_status() == "fake"
            assert module.credential_blocked() is True

# ---------------------------------------------------------------------------
# Integration marker (skipped in unit runs)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestEmbeddingIntegration:
    """Live tests — require OPENAI_API_KEY and Qdrant at :46333."""

    @pytest.mark.asyncio
    async def test_embed_query_real_vector_shape(self):
        """Real API call returns a 1536-dim vector."""
        _skip_without_real_openai_key()
        svc = EmbeddingService()
        vec = await svc.embed_query("làng chài Hàm Ninh")
        assert len(vec) == 1536
        assert all(isinstance(x, float) for x in vec)


# ---------------------------------------------------------------------------
# Integration tests — corpus indexing and semantic search
# ---------------------------------------------------------------------------

def _is_real_api_key() -> bool:
    """Return True when OPENAI_API_KEY is not empty or a known placeholder."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    placeholder_markers = ("fake", "[REDACTED", "REDACTED", "xxxx", "<")
    placeholder_suffixes = (">", "xxxx")
    return (
        bool(key)
        and not key.startswith(placeholder_markers)
        and not key.endswith(placeholder_suffixes)
    )


@pytest.mark.integration
class TestEmbeddingIndex:
    """Prove 607 proposition chunks are indexed in Qdrant with correct named-vector shape."""

    @pytest.mark.asyncio
    async def test_embed_endpoint_indexes_named_dense_collection_idempotently(self):
        """POST /admin/embed twice keeps the live named-vector corpus at 321 points."""
        _skip_without_real_openai_key()

        first_body = await _post_admin_embed()
        assert first_body["total_chunks"] == EXPECTED_CORPUS_CHUNKS

        svc = QdrantService(url=_qdrant_url())
        first_info = await svc.collection_info()
        _assert_collection_info_indexed(first_info)

        second_body = await _post_admin_embed()
        assert second_body["total_chunks"] == EXPECTED_CORPUS_CHUNKS
        second_info = await svc.collection_info()
        _assert_collection_info_indexed(second_info)
        assert second_info["points_count"] == first_info["points_count"] == EXPECTED_CORPUS_CHUNKS

    @pytest.mark.asyncio
    async def test_search_result_exposes_named_dense_vector_dimension(self):
        """Search result vectors include the 1536-dimensional named dense vector."""
        _skip_without_real_openai_key()

        await _post_admin_embed()
        svc = QdrantService(url=_qdrant_url())
        results = await svc.search(query_vector=[0.0] * VECTOR_SIZE, top_k=1)
        assert len(results) >= 1, "Expected at least one Qdrant result after embedding"
        dense = _extract_dense_vector(results[0].vector)
        assert len(dense) == VECTOR_SIZE

@pytest.mark.integration
class TestSemanticSearch:
    """Prove semantic search returns relevant Hàm Ninh results."""

    @pytest.mark.asyncio
    async def test_ham_ninh_query_returns_relevant_chunks(self):
        """'làng chài Hàm Ninh' query returns ≥3 results mentioning Hàm Ninh."""
        _skip_without_real_openai_key()

        qdrant_url = _qdrant_url()
        embed_svc = EmbeddingService()
        qdrant_svc = QdrantService(url=qdrant_url)
        await _post_admin_embed()

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
        _skip_without_real_openai_key()

        qdrant_url = _qdrant_url()
        embed_svc = EmbeddingService()
        qdrant_svc = QdrantService(url=qdrant_url)
        await _post_admin_embed()

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
        _skip_without_real_openai_key()

        qdrant_url = _qdrant_url()
        embed_svc = EmbeddingService()
        qdrant_svc = QdrantService(url=qdrant_url)
        await _post_admin_embed()

        query_vec = await embed_svc.embed_query("du lịch Phú Quốc")
        results = await qdrant_svc.search(query_vec, top_k=5)
        assert len(results) == 5
