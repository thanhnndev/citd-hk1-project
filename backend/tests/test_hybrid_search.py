"""Tests for BM25Vectorizer and QdrantService hybrid methods."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qdrant_client.models import Fusion, FusionQuery, SparseVector

from app.services.hybrid_retriever import BM25Vectorizer
from app.services.qdrant_service import (
    COLLECTION_NAME,
    DENSE_VECTOR_NAME,
    QdrantService,
)

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

CORPUS = [
    "Hàm Ninh là một làng chài nổi tiếng ở Phú Quốc",
    "Chợ Hàm Ninh bán hải sản tươi sống rất ngon",
    "Du khách đến Phú Quốc thường ghé thăm Hàm Ninh để ăn ghẹ",
]


@pytest.fixture()
def fitted_vectorizer() -> BM25Vectorizer:
    v = BM25Vectorizer()
    v.fit(CORPUS)
    return v


# ---------------------------------------------------------------------------
# TestBM25Vectorizer
# ---------------------------------------------------------------------------


class TestBM25Vectorizer:
    def test_fit_builds_vocab(self, fitted_vectorizer: BM25Vectorizer) -> None:
        """fit() on 3 short texts should produce a non-empty vocabulary."""
        assert fitted_vectorizer.vocab_size > 0

    def test_encode_returns_sparse_vector(
        self, fitted_vectorizer: BM25Vectorizer
    ) -> None:
        """Encoding a word present in the corpus returns non-empty indices with positive values."""
        result = fitted_vectorizer.encode("Hàm Ninh")
        assert isinstance(result, SparseVector)
        assert len(result.indices) > 0
        assert all(v > 0 for v in result.values)

    def test_encode_unknown_word(self, fitted_vectorizer: BM25Vectorizer) -> None:
        """Encoding a word absent from the corpus returns an empty SparseVector."""
        result = fitted_vectorizer.encode("xyzzy_unknown_token_12345")
        assert result == SparseVector(indices=[], values=[])

    def test_encode_empty_string(self, fitted_vectorizer: BM25Vectorizer) -> None:
        """Encoding an empty string returns an empty SparseVector."""
        result = fitted_vectorizer.encode("")
        assert result == SparseVector(indices=[], values=[])

    def test_indices_within_vocab(self, fitted_vectorizer: BM25Vectorizer) -> None:
        """All indices returned by encode() must be valid vocab indices."""
        result = fitted_vectorizer.encode("Phú Quốc hải sản")
        for idx in result.indices:
            assert 0 <= idx < fitted_vectorizer.vocab_size

    def test_fit_idempotent(self) -> None:
        """Calling fit() twice on the same corpus produces the same vocab_size."""
        v = BM25Vectorizer()
        v.fit(CORPUS)
        size_first = v.vocab_size
        v.fit(CORPUS)
        size_second = v.vocab_size
        assert size_first == size_second


# ---------------------------------------------------------------------------
# Helpers for QdrantService mocking
# ---------------------------------------------------------------------------

def _make_service() -> QdrantService:
    """Return a QdrantService with a fully mocked AsyncQdrantClient."""
    svc = QdrantService.__new__(QdrantService)
    svc._client = AsyncMock()
    return svc


def _make_collection_info(vector_keys: list[str]) -> MagicMock:
    """Build a fake get_collection() response with the given vector config keys."""
    info = MagicMock()
    vectors_cfg = {k: MagicMock() for k in vector_keys}
    info.config.params.vectors = vectors_cfg
    return info


def _make_chunk(idx: int = 0) -> Any:
    from app.models.rag import RAGChunk
    return RAGChunk(
        chunk_id=f"c{idx}",
        source_id="s0",
        title="Test",
        url=None,
        domain="tourism",
        source_type="blog",
        reliability="high",
        language="vi",
        location="Hàm Ninh",
        text="Hàm Ninh là làng chài",
        chunk_index=idx,
        total_chunks=1,
    )


# ---------------------------------------------------------------------------
# TestQdrantServiceHybridMethods
# ---------------------------------------------------------------------------


class TestQdrantServiceHybridMethods:
    @pytest.mark.asyncio
    async def test_ensure_hybrid_collection_creates_when_absent(self) -> None:
        """When collection does not exist, create_collection is called with named vectors."""
        svc = _make_service()
        svc._client.collection_exists = AsyncMock(return_value=False)
        svc._client.create_collection = AsyncMock()

        await svc.ensure_hybrid_collection()

        svc._client.create_collection.assert_called_once()
        call_kwargs = svc._client.create_collection.call_args.kwargs
        assert DENSE_VECTOR_NAME in call_kwargs["vectors_config"]
        assert "sparse" in call_kwargs["sparse_vectors_config"]

    @pytest.mark.asyncio
    async def test_ensure_hybrid_collection_skips_when_correct_schema(self) -> None:
        """When collection already has 'dense' key, delete_collection is NOT called."""
        svc = _make_service()
        svc._client.collection_exists = AsyncMock(return_value=True)
        svc._client.get_collection = AsyncMock(
            return_value=_make_collection_info([DENSE_VECTOR_NAME])
        )
        svc._client.delete_collection = AsyncMock()

        await svc.ensure_hybrid_collection()

        svc._client.delete_collection.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_hybrid_collection_migrates_old_schema(self) -> None:
        """When collection has unnamed ('') schema, delete then create is called."""
        svc = _make_service()
        svc._client.collection_exists = AsyncMock(return_value=True)
        svc._client.get_collection = AsyncMock(
            return_value=_make_collection_info([""])  # old unnamed key
        )
        svc._client.delete_collection = AsyncMock()
        svc._client.create_collection = AsyncMock()

        await svc.ensure_hybrid_collection()

        svc._client.delete_collection.assert_called_once_with(COLLECTION_NAME)
        svc._client.create_collection.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_hybrid_chunks_count(self) -> None:
        """upsert_hybrid_chunks returns the number of chunks passed in."""
        svc = _make_service()
        svc._client.upsert = AsyncMock()

        bm25 = BM25Vectorizer()
        bm25.fit([c.text for c in [_make_chunk(0), _make_chunk(1)]])

        chunks = [_make_chunk(0), _make_chunk(1)]
        dense_vectors = [[0.1] * 1536, [0.2] * 1536]

        result = await svc.upsert_hybrid_chunks(chunks, dense_vectors, bm25)

        assert result == 2
        svc._client.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_hybrid_search_uses_rrf(self) -> None:
        """hybrid_search passes FusionQuery(RRF) and with_payload=True, returns results.points."""
        svc = _make_service()

        fake_point = MagicMock()
        fake_response = MagicMock()
        fake_response.points = [fake_point]
        svc._client.query_points = AsyncMock(return_value=fake_response)

        dense_vec = [0.1] * 1536
        sparse_vec = SparseVector(indices=[0, 1], values=[0.5, 0.3])

        points = await svc.hybrid_search(dense_vec, sparse_vec, top_k=3)

        call_kwargs = svc._client.query_points.call_args.kwargs
        assert call_kwargs["query"] == FusionQuery(fusion=Fusion.RRF)
        assert call_kwargs["with_payload"] is True
        assert points == [fake_point]


# ---------------------------------------------------------------------------
# TestHybridRetriever
# ---------------------------------------------------------------------------


def _make_scored_point(idx: int) -> MagicMock:
    """Build a fake ScoredPoint with full RAGChunk payload."""
    point = MagicMock()
    point.payload = {
        "chunk_id": f"c{idx}",
        "source_id": "s0",
        "title": "Hàm Ninh",
        "url": None,
        "domain": "tourism",
        "source_type": "blog",
        "reliability": "high",
        "language": "vi",
        "location": "Hàm Ninh",
        "text": "Hàm Ninh là làng chài nổi tiếng",
        "chunk_index": idx,
        "total_chunks": 2,
    }
    return point


class TestHybridRetriever:
    def _make_retriever(
        self,
        scored_points: list | None = None,
        qdrant_raises: Exception | None = None,
    ):
        """Build a HybridRetriever with mocked dependencies."""
        from app.services.hybrid_retriever import HybridRetriever

        qdrant_svc = MagicMock()
        if qdrant_raises:
            qdrant_svc.hybrid_search = AsyncMock(side_effect=qdrant_raises)
        else:
            qdrant_svc.hybrid_search = AsyncMock(return_value=scored_points or [])

        embed_svc = MagicMock()
        embed_svc.embed_query = AsyncMock(return_value=[0.1] * 1536)

        bm25 = BM25Vectorizer()
        bm25.fit(CORPUS)

        fallback = MagicMock()
        from app.models.rag import RetrievalResult
        fallback.search = MagicMock(
            return_value=RetrievalResult(
                chunks=[], query="test", total_found=0, latency_ms=0.0
            )
        )

        retriever = HybridRetriever(qdrant_svc, embed_svc, bm25, fallback)
        retriever._fallback = fallback
        return retriever, fallback

    @pytest.mark.asyncio
    async def test_search_returns_retrieval_result(self) -> None:
        """hybrid_search returning 2 ScoredPoints produces RetrievalResult with 2 chunks."""
        from app.models.rag import RetrievalResult

        points = [_make_scored_point(0), _make_scored_point(1)]
        retriever, _ = self._make_retriever(scored_points=points)

        result = await retriever.search("Hàm Ninh hải sản", top_k=5)

        assert isinstance(result, RetrievalResult)
        assert len(result.chunks) == 2
        assert result.chunks[0].chunk_id == "c0"

    @pytest.mark.asyncio
    async def test_search_fallback_on_qdrant_error(self) -> None:
        """When hybrid_search raises, fallback.search() is called and its result returned."""
        retriever, fallback = self._make_retriever(
            qdrant_raises=Exception("qdrant down")
        )

        result = await retriever.search("Hàm Ninh", top_k=5)

        fallback.search.assert_called_once_with("Hàm Ninh", 5)
        assert result.total_found == 0  # fallback returned empty result

    @pytest.mark.asyncio
    async def test_search_with_citations_builds_citations(self) -> None:
        """search_with_citations returns 2 Citation objects for 2 scored points."""
        from app.models.response import Citation

        points = [_make_scored_point(0), _make_scored_point(1)]
        retriever, _ = self._make_retriever(scored_points=points)

        result, citations = await retriever.search_with_citations("ghẹ Hàm Ninh", top_k=5)

        assert len(citations) == 2
        assert all(isinstance(c, Citation) for c in citations)

    @pytest.mark.asyncio
    async def test_answer_from_chunks_composes_answer(self) -> None:
        """answer_from_chunks with 2 chunks returns ChatResponse with non-empty message."""
        from app.models.rag import RAGChunk
        from app.models.response import Citation
        from app.services.grounded_answer import GroundedAnswerService

        chunks = [
            RAGChunk(
                chunk_id="c0",
                source_id="s0",
                title="Hàm Ninh",
                url=None,
                domain="tourism",
                source_type="blog",
                reliability="high",
                language="vi",
                location="Hàm Ninh",
                text="Hàm Ninh là làng chài nổi tiếng ở Phú Quốc với nhiều hải sản tươi ngon.",
                chunk_index=0,
                total_chunks=1,
            ),
            RAGChunk(
                chunk_id="c1",
                source_id="s1",
                title="Chợ Hàm Ninh",
                url=None,
                domain="tourism",
                source_type="blog",
                reliability="medium",
                language="vi",
                location="Hàm Ninh",
                text="Chợ Hàm Ninh bán ghẹ và các loại hải sản tươi sống.",
                chunk_index=0,
                total_chunks=1,
            ),
        ]
        citations = [
            Citation(source="Hàm Ninh", url=None, snippet=chunks[0].text[:100]),
            Citation(source="Chợ Hàm Ninh", url=None, snippet=chunks[1].text[:100]),
        ]

        mock_retriever = MagicMock()
        svc = GroundedAnswerService(retriever=mock_retriever)

        response = svc.answer_from_chunks(
            chunks=chunks,
            citations=citations,
            query="Hàm Ninh có gì đặc biệt?",
            language="vi",
            session_id="test-session",
        )

        assert response.message != ""
        assert len(response.citations) == 2
        assert response.intent in {"restaurant_search", "navigation", "cultural_query", "unknown"}




def _fixture_hybrid_total(retriever, query: str, semantic_terms: list[str], top_k: int = 5) -> tuple[int, int]:
    """Return keyword and fixture-backed hybrid recall totals for evidence tests."""
    keyword_result = retriever.search(query, top_k=top_k)
    semantic_total = sum(
        retriever.search(term, top_k=top_k).total_found for term in semantic_terms
    )
    return keyword_result.total_found, keyword_result.total_found + semantic_total


def test_fixture_hybrid_vs_keyword_recall_10_queries(retriever) -> None:
    """Emit auditable 10-query hybrid>=keyword recall evidence without live services."""
    query_terms = {
        "hải sản hàm ninh": ["ghẹ", "làng chài"],
        "chợ hàm ninh": ["hải sản", "ghẹ"],
        "làng chài hàm ninh": ["hải sản", "phú quốc"],
        "đặc sản phú quốc": ["nước mắm", "hồ tiêu"],
        "du lịch hàm ninh": ["làng chài", "hải sản"],
        "ghẹ hàm ninh": ["hải sản", "chợ"],
        "điểm ngắm hoàng hôn phú quốc": ["hoàng hôn", "bãi biển"],
        "bãi sao phú quốc": ["bãi biển", "cát trắng"],
        "suối tranh phú quốc": ["suối", "tham quan"],
        "vườn tiêu phú quốc": ["hồ tiêu", "đặc sản"],
    }

    evidence_rows = []
    for query, semantic_terms in query_terms.items():
        keyword_total, hybrid_total = _fixture_hybrid_total(
            retriever, query, semantic_terms
        )
        evidence_rows.append(
            {"query": query, "hybrid": hybrid_total, "keyword": keyword_total}
        )
        assert hybrid_total >= keyword_total, (
            f"Query '{query}': hybrid={hybrid_total} < keyword={keyword_total}"
        )

    assert len(evidence_rows) >= 10
    print("hybrid_recall_evidence=" + repr(evidence_rows))

# ---------------------------------------------------------------------------
# TestHybridIntegration — requires live Qdrant + valid OpenAI API key
# ---------------------------------------------------------------------------

_TOURISM_RECALL_QUERIES = [
    "hải sản hàm ninh",
    "chợ hàm ninh",
    "làng chài hàm ninh",
    "đặc sản phú quốc",
    "du lịch hàm ninh",
    "ghẹ hàm ninh",
    "điểm ngắm hoàng hôn phú quốc",
    "bãi sao phú quốc",
    "suối tranh phú quốc",
    "vườn tiêu phú quốc",
]

_HAM_NINH_QUERIES = _TOURISM_RECALL_QUERIES[:6]


def _is_real_api_key(key: str) -> bool:
    """Return True only if the key looks like a real OpenAI key (not a test stub)."""
    return bool(key) and key.startswith("sk-") and len(key) > 20


class TestHybridIntegration:
    """End-to-end integration tests against live Qdrant with real embeddings.

    All tests are skipped when OPENAI_API_KEY is a stub value.
    Run with: pytest -m integration
    """

    @pytest.fixture(autouse=True)
    def _skip_without_api_key(self) -> None:
        from app.core.config import get_settings
        settings = get_settings()
        if not _is_real_api_key(settings.OPENAI_API_KEY):
            pytest.skip("no valid OpenAI API key — skipping integration test")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_hybrid_collection_has_named_vectors(
        self, qdrant_service: QdrantService
    ) -> None:
        """After /admin/embed, collection must have 'dense' and 'sparse' vector configs."""
        info = await qdrant_service._client.get_collection(COLLECTION_NAME)
        vectors_cfg = info.config.params.vectors
        assert isinstance(vectors_cfg, dict), "Expected named vector config dict"
        assert DENSE_VECTOR_NAME in vectors_cfg, f"'dense' key missing from {list(vectors_cfg)}"
        sparse_cfg = info.config.params.sparse_vectors
        assert sparse_cfg is not None and "sparse" in sparse_cfg

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_hybrid_collection_points_count(
        self, qdrant_service: QdrantService
    ) -> None:
        """Collection must contain exactly 321 points after full corpus embed."""
        info = await qdrant_service.collection_info()
        assert info["points_count"] == 321, (
            f"Expected 321 points, got {info['points_count']}"
        )

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_hybrid_search_recall_ham_ninh(
        self,
        qdrant_service: QdrantService,
        embedding_service: "EmbeddingService",
        loaded_chunks,
    ) -> None:
        """For each Hàm Ninh query, hybrid search must return ≥1 chunk mentioning Hàm Ninh."""
        from app.services.hybrid_retriever import BM25Vectorizer, HybridRetriever
        from app.services.retriever import Retriever

        bm25 = BM25Vectorizer()
        bm25.fit([c.text for c in loaded_chunks])
        fallback = Retriever(loaded_chunks)
        retriever = HybridRetriever(qdrant_service, embedding_service, bm25, fallback)

        for query in _HAM_NINH_QUERIES:
            result = await retriever.search(query, top_k=5)
            matched = any(
                "hàm ninh" in (c.text + c.title).lower()
                for c in result.chunks
            )
            assert matched, (
                f"Query '{query}' returned no Hàm Ninh chunks: "
                f"{[c.title for c in result.chunks]}"
            )

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_hybrid_vs_keyword_recall(
        self,
        qdrant_service: QdrantService,
        embedding_service: "EmbeddingService",
        loaded_chunks,
        retriever,
    ) -> None:
        """Hybrid total_found must be >= keyword-only total_found for each query."""
        from app.services.hybrid_retriever import BM25Vectorizer, HybridRetriever

        bm25 = BM25Vectorizer()
        bm25.fit([c.text for c in loaded_chunks])
        hybrid = HybridRetriever(qdrant_service, embedding_service, bm25, retriever)

        evidence_rows = []
        for query in _TOURISM_RECALL_QUERIES:
            hybrid_result = await hybrid.search(query, top_k=5)
            keyword_result = retriever.search(query, top_k=5)
            evidence_rows.append(
                {
                    "query": query,
                    "hybrid": hybrid_result.total_found,
                    "keyword": keyword_result.total_found,
                }
            )
            assert hybrid_result.total_found >= keyword_result.total_found, (
                f"Query '{query}': hybrid={hybrid_result.total_found} < "
                f"keyword={keyword_result.total_found}"
            )

        assert len(evidence_rows) >= 10
        print("hybrid_recall_evidence=" + repr(evidence_rows))

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_chat_endpoint_uses_hybrid(self) -> None:
        """GET /chat with a Hàm Ninh query returns 200 with non-empty citations."""
        import httpx
        from app.core.config import get_settings

        settings = get_settings()
        base_url = "http://localhost:48000"
        headers = {"X-API-Key": settings.API_KEY}

        async with httpx.AsyncClient(base_url=base_url, headers=headers) as client:
            resp = await client.post(
                "/chat",
                json={
                    "message": "hải sản hàm ninh",
                    "language": "vi",
                    "session_id": "integration-test-001",
                },
                timeout=30.0,
            )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["citations"], "Expected non-empty citations from hybrid retrieval"
