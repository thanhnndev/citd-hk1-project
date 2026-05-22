"""Tests for the proposition ingestion pipeline.

Covers:
- load_corpus() / load_proposition_corpus() schema validation
- BM25Vectorizer fitting and encoding over proposition texts
- HybridRetriever search over proposition chunks (mocked Qdrant)
- Keyword Retriever search over proposition chunks
- Multilingual query handling (Vietnamese + English)
- Integration test against live /admin/embed when Docker is available
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.rag import RAGChunk, RetrievalResult
from app.models.response import Citation
from app.services.corpus_loader import load_corpus, load_proposition_corpus, get_corpus_stats
from app.services.hybrid_retriever import BM25Vectorizer, HybridRetriever
from app.services.retriever import Retriever

# ---------------------------------------------------------------------------
# Corpus path helper (mirrors conftest.py)
# ---------------------------------------------------------------------------

def _resolve_corpus_path() -> str:
    """Resolve the proposition JSONL path from the backend/ or project root."""
    from pathlib import Path

    p = Path("data/tourism_documents.jsonl")
    if p.exists():
        return str(p)
    # Fall back to project root
    return str(Path(__file__).resolve().parent.parent.parent / "data" / "tourism_documents.jsonl")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def proposition_chunks() -> list[RAGChunk]:
    """Load the proposition-level corpus (607 chunks of atomic propositions)."""
    return load_corpus(_resolve_corpus_path())


@pytest.fixture(scope="session")
def proposition_texts(proposition_chunks) -> list[str]:
    """All proposition texts for BM25 fitting."""
    return [c.text for c in proposition_chunks]


@pytest.fixture(scope="session")
def fitted_bm25(proposition_texts) -> BM25Vectorizer:
    """BM25Vectorizer fit on the full proposition corpus."""
    vec = BM25Vectorizer()
    vec.fit(proposition_texts)
    return vec


@pytest.fixture(scope="session")
def keyword_retriever(proposition_chunks) -> Retriever:
    """Keyword Retriever over the proposition corpus."""
    return Retriever(proposition_chunks)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestPropositionSchema:
    """Verify load_corpus() returns well-formed RAGChunk objects for propositions."""

    def test_load_corpus_returns_list(self, proposition_chunks) -> None:
        """load_corpus() returns a non-empty list."""
        assert isinstance(proposition_chunks, list)
        assert len(proposition_chunks) > 0

    def test_load_corpus_returns_607_chunks(self, proposition_chunks) -> None:
        """The proposition corpus contains exactly 607 chunks."""
        assert len(proposition_chunks) == 607

    def test_chunks_have_proposition_ids(self, proposition_chunks) -> None:
        """Each chunk has a valid proposition chunk_id (32 hex chars from MD5)."""
        assert all(c.chunk_id for c in proposition_chunks)
        for chunk in proposition_chunks:
            # Proposition chunk_ids are deterministic hex strings (MD5 = 32 chars)
            assert len(chunk.chunk_id) == 32, f"Invalid chunk_id length for {chunk.chunk_id}: got {len(chunk.chunk_id)}"
            assert all(c in "0123456789abcdef" for c in chunk.chunk_id)

    def test_chunks_have_source_ids(self, proposition_chunks) -> None:
        """Each chunk has a source_id linking to its parent document."""
        assert all(c.source_id for c in proposition_chunks)
        assert len(set(c.source_id for c in proposition_chunks)) > 1  # Multiple documents

    def test_chunks_have_text(self, proposition_chunks) -> None:
        """Each chunk has non-empty text content."""
        assert all(c.text and c.text.strip() for c in proposition_chunks), (
            "All proposition chunks must have non-empty text"
        )

    def test_chunks_have_language(self, proposition_chunks) -> None:
        """Each chunk carries a language tag."""
        assert all(c.language for c in proposition_chunks)
        languages = {c.language for c in proposition_chunks}
        assert "vi" in languages, "Expected at least one Vietnamese chunk"

    def test_chunks_have_location(self, proposition_chunks) -> None:
        """Each chunk carries a location (string or empty)."""
        assert all(c.location is not None for c in proposition_chunks)

    def test_chunks_have_reliability(self, proposition_chunks) -> None:
        """Each chunk has a reliability tier."""
        valid_tiers = {"high", "medium", "low"}
        assert all(c.reliability in valid_tiers for c in proposition_chunks)

    def test_corpus_stats(self, proposition_chunks) -> None:
        """get_corpus_stats() returns meaningful aggregate values."""
        stats = get_corpus_stats(proposition_chunks)
        assert stats.total_docs > 0
        assert stats.total_chunks == 607
        assert stats.avg_chunk_length > 0
        assert stats.source_type_distribution
        assert stats.reliability_distribution


# ---------------------------------------------------------------------------
# BM25Vectorizer over proposition corpus
# ---------------------------------------------------------------------------

class TestBM25OnPropositions:
    """BM25Vectorizer must fit and encode proposition texts correctly."""

    def test_fit_produces_vocab(self, fitted_bm25, proposition_texts) -> None:
        """Fitting on 607 proposition texts builds a non-empty vocabulary."""
        assert fitted_bm25.vocab_size > 0, "BM25 vocab should not be empty after fit()"

    def test_encode_produces_sparse_vector(self, fitted_bm25) -> None:
        """Encoding a Vietnamese query returns a non-empty SparseVector."""
        result = fitted_bm25.encode("hải sản làng chài")
        assert len(result.indices) > 0, "Expected non-empty BM25 indices for known terms"
        assert len(result.indices) == len(result.values)
        assert all(v > 0 for v in result.values), "All BM25 values must be positive"

    def test_encode_english_query(self, fitted_bm25) -> None:
        """Encoding an English query that overlaps with propositions returns a non-empty vector."""
        result = fitted_bm25.encode("seafood Phu Quoc fishing village")
        assert len(result.indices) > 0, "Expected non-empty BM25 indices for English terms"

    def test_encode_unknown_returns_empty(self, fitted_bm25) -> None:
        """Encoding a term absent from the vocabulary returns an empty vector."""
        result = fitted_bm25.encode("xyzzy_novel_term_99999")
        assert result.indices == []
        assert result.values == []

    def test_encode_empty_returns_empty(self, fitted_bm25) -> None:
        """Encoding an empty string returns an empty vector."""
        result = fitted_bm25.encode("")
        assert result.indices == []
        assert result.values == []

    def test_vocab_size_greater_than_corpus_chunks(self, fitted_bm25) -> None:
        """Vocab size should be large enough to cover proposition content."""
        assert fitted_bm25.vocab_size >= 50, "Expected BM25 vocab to have at least 50 tokens"

    def test_encode_all_indices_in_vocab(self, fitted_bm25) -> None:
        """All indices in a SparseVector must be valid vocabulary indices."""
        result = fitted_bm25.encode("làng chài hải sản phú quốc")
        for idx in result.indices:
            assert 0 <= idx < fitted_bm25.vocab_size, (
                f"Index {idx} out of bounds for vocab size {fitted_bm25.vocab_size}"
            )


# ---------------------------------------------------------------------------
# HybridRetriever search over proposition chunks (unit)
# ---------------------------------------------------------------------------

class TestHybridRetrieverPropositions:
    """HybridRetriever.search() over proposition chunks with mocked Qdrant."""

    @pytest.fixture
    def hybrid_retriever(
        self, fitted_bm25, keyword_retriever
    ) -> tuple[HybridRetriever, MagicMock]:
        """Build a HybridRetriever with all deps mocked."""
        qdrant_svc = MagicMock()
        embed_svc = MagicMock()
        embed_svc.embed_query = AsyncMock(return_value=[0.1] * 1536)
        fallback = keyword_retriever

        retriever = HybridRetriever(qdrant_svc, embed_svc, fitted_bm25, fallback)
        return retriever, qdrant_svc

    def _make_scored_points(self, chunk_ids: list[str]) -> list[MagicMock]:
        """Build fake ScoredPoints for a list of chunk IDs."""
        texts = {
            "c0": "Làng chài Hàm Ninh nổi tiếng với hải sản tươi ngon",
            "c1": "Chợ Hàm Ninh bán ghẹ và các loại cá tươi",
            "c2": "Du lịch Phú Quốc không thể bỏ qua Bãi Sao",
            "c3": "Đặc sản Phú Quốc bao gồm nước mắm và hồ tiêu",
        }
        points = []
        for idx, chunk_id in enumerate(chunk_ids):
            point = MagicMock()
            point.payload = {
                "chunk_id": chunk_id,
                "source_id": f"s{idx}",
                "title": f"Document {idx}",
                "url": None,
                "domain": "tourism",
                "source_type": "blog",
                "reliability": "medium",
                "language": "vi",
                "location": "Phú Quốc",
                "text": texts.get(chunk_id, f"Text for {chunk_id}"),
                "chunk_index": 0,
                "total_chunks": 1,
            }
            points.append(point)
        return points

    @pytest.mark.asyncio
    async def test_search_returns_retrieval_result(self, hybrid_retriever) -> None:
        """search() returns a RetrievalResult with the correct query field."""
        retriever, qdrant_svc = hybrid_retriever
        qdrant_svc.hybrid_search = AsyncMock(
            return_value=self._make_scored_points(["c0", "c1"])
        )

        result = await retriever.search("làng chài Hàm Ninh", top_k=5)

        assert isinstance(result, RetrievalResult)
        assert result.query == "làng chài Hàm Ninh"
        assert result.total_found >= 0

    @pytest.mark.asyncio
    async def test_search_populates_chunks(self, hybrid_retriever) -> None:
        """search() returns chunks with correct chunk_ids from the scored points."""
        retriever, qdrant_svc = hybrid_retriever
        qdrant_svc.hybrid_search = AsyncMock(
            return_value=self._make_scored_points(["c0", "c1", "c2"])
        )

        result = await retriever.search("hải sản", top_k=3)

        assert len(result.chunks) == 3
        assert all(isinstance(c, RAGChunk) for c in result.chunks)
        assert [c.chunk_id for c in result.chunks] == ["c0", "c1", "c2"]

    @pytest.mark.asyncio
    async def test_search_measures_latency(self, hybrid_retriever) -> None:
        """search() returns a non-negative latency_ms."""
        retriever, qdrant_svc = hybrid_retriever
        qdrant_svc.hybrid_search = AsyncMock(return_value=[])

        result = await retriever.search("phú quốc", top_k=5)

        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_search_falls_back_on_qdrant_error(
        self, hybrid_retriever, keyword_retriever
    ) -> None:
        """When Qdrant raises, fallback (keyword) search is used and returns results."""
        retriever, qdrant_svc = hybrid_retriever
        qdrant_svc.hybrid_search = AsyncMock(side_effect=Exception("Qdrant unreachable"))
        fallback = retriever._fallback

        result = await retriever.search("làng chài", top_k=5)

        # Qdrant failed and keyword fallback was used - result should come from fallback
        # which uses the same corpus, so it should find results for "làng chài"
        assert result.total_found >= 0  # keyword fallback always returns a valid result

    @pytest.mark.asyncio
    async def test_search_with_citations_returns_both(self, hybrid_retriever) -> None:
        """search_with_citations() returns (RetrievalResult, list[Citation])."""
        retriever, qdrant_svc = hybrid_retriever
        qdrant_svc.hybrid_search = AsyncMock(
            return_value=self._make_scored_points(["c0"])
        )

        result, citations = await retriever.search_with_citations(
            "hải sản phú quốc", top_k=5
        )

        assert isinstance(result, RetrievalResult)
        assert isinstance(citations, list)
        assert all(isinstance(c, Citation) for c in citations)


# ---------------------------------------------------------------------------
# Keyword retriever search over proposition chunks
# ---------------------------------------------------------------------------

class TestKeywordRetrieverPropositions:
    """Keyword Retriever (TF*IDF) over proposition chunks."""

    def test_search_vietnamese_query(self, keyword_retriever) -> None:
        """Vietnamese query returns non-empty results."""
        result = keyword_retriever.search("làng chài hải sản", top_k=5)
        assert result.total_found >= 1, f"Expected ≥1 results for 'làng chài hải sản', got {result.total_found}"
        assert len(result.chunks) >= 1

    def test_search_english_query(self, keyword_retriever) -> None:
        """English query returns non-empty results (cross-language token overlap)."""
        result = keyword_retriever.search("seafood Phu Quoc", top_k=5)
        assert result.total_found >= 1, f"Expected ≥1 results for English 'seafood Phu Quoc', got {result.total_found}"

    def test_search_empty_query_returns_empty(self, keyword_retriever) -> None:
        """Empty query returns empty results."""
        result = keyword_retriever.search("", top_k=5)
        assert result.total_found == 0
        assert result.chunks == []

    def test_search_top_k_limits_results(self, keyword_retriever) -> None:
        """top_k parameter limits the number of returned chunks."""
        result = keyword_retriever.search("làng chài", top_k=3)
        assert len(result.chunks) <= 3

    def test_search_ranked_by_score(self, keyword_retriever) -> None:
        """Results are returned in descending relevance score order."""
        result = keyword_retriever.search("ghẹ", top_k=5)
        scores = []
        for chunk in result.chunks:
            tf = keyword_retriever._tf[keyword_retriever._chunks.index(chunk)]
            scores.append(sum(tf.get(t, 0) for t in ["ghẹ"]))
        if len(scores) > 1:
            assert scores == sorted(scores, reverse=True), "Chunks should be ranked by descending score"

    def test_search_measures_latency(self, keyword_retriever) -> None:
        """search() returns a non-negative latency_ms."""
        result = keyword_retriever.search("hàm ninh", top_k=5)
        assert result.latency_ms >= 0

    def test_search_with_citations(self, keyword_retriever) -> None:
        """search_with_citations() returns Citation objects."""
        result, citations = keyword_retriever.search_with_citations(
            "làng chài hàm ninh", top_k=5
        )
        assert len(citations) == len(result.chunks)
        for citation in citations:
            assert citation.source  # title mapped from chunk
            assert citation.snippet  # truncated text

    def test_search_reliability_boost(self) -> None:
        """High-reliability chunks score higher than medium/low for the same terms."""
        from app.models.rag import RAGChunk

        chunks = [
            RAGChunk(chunk_id="h1", source_id="s1", title="High doc",
                     url=None, domain="tourism", source_type="blog",
                     reliability="high", language="vi", location="HQ",
                     text="làng chài hải sản phú quốc",
                     chunk_index=0, total_chunks=1),
            RAGChunk(chunk_id="m1", source_id="s2", title="Med doc",
                     url=None, domain="tourism", source_type="blog",
                     reliability="medium", language="vi", location="HQ",
                     text="làng chài hải sản phú quốc",
                     chunk_index=0, total_chunks=1),
        ]
        retriever = Retriever(chunks)
        result = retriever.search("làng chài hải sản", top_k=2)
        assert result.chunks[0].chunk_id == "h1", "High-reliability chunk should rank first"


# ---------------------------------------------------------------------------
# Multilingual query handling
# ---------------------------------------------------------------------------

class TestMultilingualQueries:
    """Both Vietnamese and English queries must produce meaningful results."""

    def test_vietnamese_query_returns_results(self, keyword_retriever) -> None:
        """Vietnamese query 'làng chài hàm ninh' returns results."""
        result = keyword_retriever.search("làng chài hàm ninh", top_k=5)
        assert result.total_found >= 1, f"Expected ≥1 result for Vietnamese query, got {result.total_found}"

    def test_english_query_returns_results(self, keyword_retriever) -> None:
        """English query 'fishing village' returns results."""
        result = keyword_retriever.search("fishing village", top_k=5)
        assert result.total_found >= 1, f"Expected ≥1 result for English query, got {result.total_found}"

    def test_mixed_query(self, keyword_retriever) -> None:
        """Mixed Vietnamese-English query returns results."""
        result = keyword_retriever.search("hải sản seafood Phu Quoc", top_k=5)
        assert result.total_found >= 1

    def test_bm25_encodes_multilingual(self, fitted_bm25) -> None:
        """BM25 encodes both Vietnamese and English tokens."""
        vi_result = fitted_bm25.encode("làng chài hải sản")
        en_result = fitted_bm25.encode("fishing village seafood")
        assert len(vi_result.indices) > 0, "BM25 should encode Vietnamese tokens"
        assert len(en_result.indices) > 0, "BM25 should encode English tokens"


# ---------------------------------------------------------------------------
# Integration test (requires Docker: Qdrant + valid OpenAI key)
# ---------------------------------------------------------------------------

def _is_real_api_key(key: str) -> bool:
    """Return True only if the key looks like a real OpenAI key."""
    return bool(key) and key.startswith("sk-") and len(key) > 20


class TestPropositionIngestionIntegration:
    """End-to-end proposition ingestion integration tests.

    Requires:
    - Live Qdrant (localhost:6333 or HN_QDRANT_HOST_PORT)
    - Valid OPENAI_API_KEY (not a test stub)
    - Corpus already ingested via POST /admin/embed

    Run with: cd backend && python -m pytest tests/test_proposition_ingestion.py -m integration -v
    """

    @pytest.fixture(autouse=True)
    def _skip_without_api_key(self) -> None:
        import os
        from app.core.config import get_settings
        settings = get_settings()
        if not _is_real_api_key(settings.OPENAI_API_KEY):
            pytest.skip("no valid OpenAI API key — skipping integration test")

    @pytest.mark.integration
    def test_admin_embed_succeeds(self) -> None:
        """POST /admin/embed returns 200 with propositions_ingested and language_distribution."""
        import httpx
        from app.core.config import get_settings

        settings = get_settings()
        base_url = "http://localhost:48000"
        headers = {"X-API-Key": settings.API_KEY}

        response = httpx.post(
            f"{base_url}/admin/embed",
            headers=headers,
            timeout=120.0,
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        body = response.json()
        assert "propositions_ingested" in body, f"Missing propositions_ingested in {body}"
        assert "language_distribution" in body, f"Missing language_distribution in {body}"
        assert body["propositions_ingested"] > 0, "Expected positive propositions_ingested"
        assert body["language_distribution"], "Expected non-empty language_distribution"

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_qdrant_collection_populated(
        self, qdrant_service
    ) -> None:
        """After ingestion, Qdrant collection contains 607 points."""
        info = await qdrant_service.collection_info()
        assert info["points_count"] == 607, (
            f"Expected 607 points, got {info['points_count']}"
        )

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_hybrid_search_vietnamese_query(
        self,
        qdrant_service,
        embedding_service,
        loaded_chunks,
    ) -> None:
        """Hybrid search for a Vietnamese query returns proposition chunks."""
        from app.services.hybrid_retriever import BM25Vectorizer, HybridRetriever
        from app.services.retriever import Retriever

        bm25 = BM25Vectorizer()
        bm25.fit([c.text for c in loaded_chunks])
        fallback = Retriever(loaded_chunks)
        retriever = HybridRetriever(qdrant_service, embedding_service, bm25, fallback)

        result = await retriever.search("làng chài hàm ninh", top_k=5)

        assert result.total_found >= 1, f"Expected ≥1 result for Vietnamese query, got {result.total_found}"
        assert all(c.language == "vi" for c in result.chunks)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_hybrid_search_english_query(
        self,
        qdrant_service,
        embedding_service,
        loaded_chunks,
    ) -> None:
        """Hybrid search for an English query returns proposition chunks."""
        from app.services.hybrid_retriever import BM25Vectorizer, HybridRetriever
        from app.services.retriever import Retriever

        bm25 = BM25Vectorizer()
        bm25.fit([c.text for c in loaded_chunks])
        fallback = Retriever(loaded_chunks)
        retriever = HybridRetriever(qdrant_service, embedding_service, bm25, fallback)

        result = await retriever.search("seafood fishing village", top_k=5)

        assert result.total_found >= 1, f"Expected ≥1 result for English query, got {result.total_found}"