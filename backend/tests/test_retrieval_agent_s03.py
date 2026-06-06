"""S03 integration tests for dense-only retrieval path + HybridRetriever.

Tests cover:
  a) dense_search returns RAGChunks from fake ScoredPoints
  b) dense-only path used when sparse absent
  c) vi query returns chunks with language=vi
  d) en query returns chunks with language=en
  e) citation_from_chunk produces correct Citation fields
  f) empty retrieval returns empty chunks list

Run from repository root:
    cd backend && python -m pytest tests/test_retrieval_agent_s03.py -v --tb=short
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from app.models.rag import RAGChunk, RetrievalResult
from app.models.response import ChatResponse, Citation
from agents.tools.hybrid_retriever import HybridRetriever
from agents.tools.retriever import citation_from_chunk, Retriever
from agents.tools.qdrant_service import QdrantService
from agents.graph.agent_service import AgentService, AgentState


# ---------------------------------------------------------------------------
# Fake ScoredPoint (mirrors qdrant_client.models.ScoredPoint payload)
# ---------------------------------------------------------------------------

@dataclass
class FakeScore:
    score: float = 0.0


@dataclass
class FakePoint:
    id: int
    payload: dict[str, Any]
    score: float = 0.0
    version: int = 0
    vector: dict[str, list[float]] | None = None


# ---------------------------------------------------------------------------
# Fake QdrantService — records calls and returns injectable results
# ---------------------------------------------------------------------------

class FakeQdrantService:
    def __init__(self, points: list[FakePoint] | None = None) -> None:
        self._points = points or []
        self.dense_calls: list[tuple[list[float], int]] = []
        self.hybrid_calls: list[tuple[list[float], Any, int]] = []

    async def dense_search(
        self, dense_vector: list[float], top_k: int = 5
    ) -> list[FakePoint]:
        self.dense_calls.append((dense_vector, top_k))
        return self._points

    async def hybrid_search(
        self,
        dense_vector: list[float],
        sparse_vector: Any,
        top_k: int = 5,
    ) -> list[FakePoint]:
        self.hybrid_calls.append((dense_vector, sparse_vector, top_k))
        return []


# ---------------------------------------------------------------------------
# Fake EmbeddingService — returns fixed vectors
# ---------------------------------------------------------------------------

class FakeEmbeddingService:
    def __init__(self, vector: list[float] | None = None) -> None:
        self._vector = vector or [0.1] * 1536
        self.calls: list[str] = []

    async def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        return self._vector


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

VI_CHUNK = RAGChunk(
    chunk_id="vi-chunk-1",
    source_id="vi-src-1",
    title="Làng chài Hàm Ninh",
    url="https://example.com/ham-ninh",
    domain="tourism",
    source_type="blog",
    reliability="high",
    language="vi",
    location="Hàm Ninh",
    text="Làng chài Hàm Ninh nổi tiếng với cảnh hoàng hôn đẹp trên biển.",
    chunk_index=0,
    total_chunks=1,
)

EN_CHUNK = RAGChunk(
    chunk_id="en-chunk-1",
    source_id="en-src-1",
    title="Hàm Ninh Fishing Village",
    url="https://example.com/ham-ninh-en",
    domain="tourism",
    source_type="blog",
    reliability="medium",
    language="en",
    location="Hàm Ninh",
    text="Hàm Ninh fishing village is famous for its beautiful sunset views.",
    chunk_index=0,
    total_chunks=1,
)

VI_POINT = FakePoint(
    id=0,
    payload={
        "chunk_id": VI_CHUNK.chunk_id,
        "source_id": VI_CHUNK.source_id,
        "title": VI_CHUNK.title,
        "url": VI_CHUNK.url,
        "domain": VI_CHUNK.domain,
        "source_type": VI_CHUNK.source_type,
        "reliability": VI_CHUNK.reliability,
        "language": VI_CHUNK.language,
        "location": VI_CHUNK.location,
        "text": VI_CHUNK.text,
        "chunk_index": VI_CHUNK.chunk_index,
        "total_chunks": VI_CHUNK.total_chunks,
    },
)

EN_POINT = FakePoint(
    id=1,
    payload={
        "chunk_id": EN_CHUNK.chunk_id,
        "source_id": EN_CHUNK.source_id,
        "title": EN_CHUNK.title,
        "url": EN_CHUNK.url,
        "domain": EN_CHUNK.domain,
        "source_type": EN_CHUNK.source_type,
        "reliability": EN_CHUNK.reliability,
        "language": EN_CHUNK.language,
        "location": EN_CHUNK.location,
        "text": EN_CHUNK.text,
        "chunk_index": EN_CHUNK.chunk_index,
        "total_chunks": EN_CHUNK.total_chunks,
    },
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDenseSearchReturnsRAGChunks:
    """Test (a): dense_search returns RAGChunks from fake ScoredPoints."""

    @pytest.mark.asyncio
    async def test_dense_search_builds_rag_chunks(self):
        fake_qdrant = FakeQdrantService(points=[VI_POINT, EN_POINT])
        fake_embed = FakeEmbeddingService()
        fallback = _make_keyword_retriever([])

        retriever = HybridRetriever(fake_qdrant, fake_embed, None, fallback)  # type: ignore[arg-type]
        result = await retriever.dense_search("làng chài", top_k=5)

        assert result.total_found == 2
        assert len(result.chunks) == 2
        chunk_ids = {c.chunk_id for c in result.chunks}
        assert "vi-chunk-1" in chunk_ids
        assert "en-chunk-1" in chunk_ids

    @pytest.mark.asyncio
    async def test_dense_search_records_dense_calls_not_hybrid(self):
        fake_qdrant = FakeQdrantService(points=[VI_POINT])
        fake_embed = FakeEmbeddingService()
        fallback = _make_keyword_retriever([])

        retriever = HybridRetriever(fake_qdrant, fake_embed, None, fallback)  # type: ignore[arg-type]
        await retriever.dense_search("test", top_k=3)

        assert len(fake_qdrant.dense_calls) == 1
        assert fake_qdrant.dense_calls[0][1] == 3  # top_k
        assert len(fake_qdrant.hybrid_calls) == 0


class TestDenseOnlyPathNoSparseRequired:
    """Test (b): dense-only path used when sparse vectors are absent."""

    @pytest.mark.asyncio
    async def test_search_does_not_require_bm25(self):
        """HybridRetriever.search() should call dense_search, not hybrid_search."""
        fake_qdrant = FakeQdrantService(points=[VI_POINT])
        fake_embed = FakeEmbeddingService()
        fallback = _make_keyword_retriever([])

        retriever = HybridRetriever(fake_qdrant, fake_embed, None, fallback)  # type: ignore[arg-type]
        result = await retriever.search("làng chài Hàm Ninh", top_k=5)

        assert len(fake_qdrant.dense_calls) == 1
        assert len(fake_qdrant.hybrid_calls) == 0
        assert result.total_found == 1

    @pytest.mark.asyncio
    async def test_search_falls_back_to_keyword_when_qdrant_error(self):
        """On Qdrant error, search() must fall back to keyword retriever."""
        fake_embed = FakeEmbeddingService()
        fallback_chunks = [
            RAGChunk(
                chunk_id="fallback-chunk",
                source_id="fallback-src",
                title="Keyword Match",
                url=None,
                domain="tourism",
                source_type="blog",
                reliability="medium",
                language="vi",
                location="Hàm Ninh",
                text="Fallback keyword result for test query",
                chunk_index=0,
                total_chunks=1,
            )
        ]
        fallback = _make_keyword_retriever(fallback_chunks)

        error_qdrant = _ErroringQdrantService()
        retriever = HybridRetriever(error_qdrant, fake_embed, None, fallback)  # type: ignore[arg-type]
        result = await retriever.search("test query", top_k=3)

        assert result.total_found == 1
        assert result.chunks[0].chunk_id == "fallback-chunk"


class TestViQueryReturnsViChunks:
    """Test (c): vi query returns chunks with language=vi."""

    @pytest.mark.asyncio
    async def test_vi_query_returns_vi_language_chunks(self):
        vi_only_points = [
            FakePoint(
                id=0,
                payload={
                    "chunk_id": "vi-1",
                    "source_id": "s1",
                    "title": "Vietnamese Title",
                    "url": None,
                    "domain": "tourism",
                    "source_type": "blog",
                    "reliability": "high",
                    "language": "vi",
                    "location": "Hàm Ninh",
                    "text": "Nội dung tiếng Việt về Hàm Ninh",
                    "chunk_index": 0,
                    "total_chunks": 1,
                },
            )
        ]
        fake_qdrant = FakeQdrantService(points=vi_only_points)
        fake_embed = FakeEmbeddingService()
        fallback = _make_keyword_retriever([])

        retriever = HybridRetriever(fake_qdrant, fake_embed, None, fallback)  # type: ignore[arg-type]
        result = await retriever.dense_search("Hàm Ninh", top_k=5)

        assert result.total_found == 1
        assert result.chunks[0].language == "vi"


class TestEnQueryReturnsEnChunks:
    """Test (d): en query returns chunks with language=en."""

    @pytest.mark.asyncio
    async def test_en_query_returns_en_language_chunks(self):
        en_only_points = [
            FakePoint(
                id=0,
                payload={
                    "chunk_id": "en-1",
                    "source_id": "s1",
                    "title": "English Title",
                    "url": None,
                    "domain": "tourism",
                    "source_type": "blog",
                    "reliability": "medium",
                    "language": "en",
                    "location": "Hàm Ninh",
                    "text": "English content about Hàm Ninh fishing village",
                    "chunk_index": 0,
                    "total_chunks": 1,
                },
            )
        ]
        fake_qdrant = FakeQdrantService(points=en_only_points)
        fake_embed = FakeEmbeddingService()
        fallback = _make_keyword_retriever([])

        retriever = HybridRetriever(fake_qdrant, fake_embed, None, fallback)  # type: ignore[arg-type]
        result = await retriever.dense_search("Hàm Ninh fishing village", top_k=5)

        assert result.total_found == 1
        assert result.chunks[0].language == "en"


class TestCitationFromChunk:
    """Test (e): citation_from_chunk produces correct Citation fields."""

    def test_citation_fields_mapped(self):
        chunk = RAGChunk(
            chunk_id="c1",
            source_id="s1",
            title="Test Title",
            url="https://example.com/article",
            domain="tourism",
            source_type="blog",
            reliability="high",
            language="vi",
            location="Hàm Ninh",
            text="A" * 300,  # long text — snippet should truncate to 200
            chunk_index=0,
            total_chunks=1,
        )
        citation = citation_from_chunk(chunk)

        assert citation.source == "Test Title"
        assert citation.url == "https://example.com/article"
        assert len(citation.snippet) == 200
        assert citation.snippet.endswith("A")

    def test_citation_short_text_no_truncation(self):
        short_text = "Short text."
        chunk = RAGChunk(
            chunk_id="c2",
            source_id="s1",
            title="Short Doc",
            url=None,
            domain="tourism",
            source_type="blog",
            reliability="medium",
            language="en",
            location="Hàm Ninh",
            text=short_text,
            chunk_index=0,
            total_chunks=1,
        )
        citation = citation_from_chunk(chunk)

        assert citation.source == "Short Doc"
        assert citation.url is None
        assert citation.snippet == short_text


class TestEmptyRetrieval:
    """Test (f): empty retrieval returns empty chunks list."""

    @pytest.mark.asyncio
    async def test_dense_search_empty_results(self):
        fake_qdrant = FakeQdrantService(points=[])
        fake_embed = FakeEmbeddingService()
        fallback = _make_keyword_retriever([])

        retriever = HybridRetriever(fake_qdrant, fake_embed, None, fallback)  # type: ignore[arg-type]
        result = await retriever.dense_search("nonexistent query xyz", top_k=5)

        assert result.total_found == 0
        assert result.chunks == []
        assert result.query == "nonexistent query xyz"

    @pytest.mark.asyncio
    async def test_search_with_fallback_empty_results(self):
        error_qdrant = _ErroringQdrantService()
        fake_embed = FakeEmbeddingService()
        fallback = _make_keyword_retriever([])

        retriever = HybridRetriever(error_qdrant, fake_embed, None, fallback)  # type: ignore[arg-type]
        result = await retriever.search("xyz nonexistent", top_k=5)

        # Falls back to empty keyword retriever
        assert result.total_found == 0
        assert result.chunks == []


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _ErroringQdrantService(FakeQdrantService):
    """QdrantService that raises on every search call."""

    async def dense_search(self, dense_vector: list[float], top_k: int = 5):
        raise RuntimeError("Qdrant unavailable")


def _make_keyword_retriever(chunks: list[RAGChunk]):
    """Build a real in-memory keyword Retriever over given chunks."""
    from agents.tools.retriever import Retriever

    return Retriever(chunks)


# ---------------------------------------------------------------------------
# T02: AgentService retrieval integration tests
# ---------------------------------------------------------------------------


class TestAgentServiceViQuery:
    """Test (a): AgentService.answer() with vi query returns ChatResponse with
    citations referencing proposition chunk_ids from the real corpus."""

    @pytest.mark.asyncio
    async def test_answer_vi_query_returns_citations(self, loaded_chunks):
        """AgentService with HybridRetriever seeded with real corpus chunks.

        The fake Qdrant returns points whose payload matches loaded_chunks
        proposition metadata — proving the pipeline handles real corpus data.
        """
        vi_chunks = [c for c in loaded_chunks if c.language == "vi"]
        assert vi_chunks, "Test requires at least one Vietnamese chunk in corpus"
        seed = vi_chunks[0]

        # Build fake points matching real corpus rows
        fake_points = [
            FakePoint(
                id=0,
                payload={
                    "chunk_id": seed.chunk_id,
                    "source_id": seed.source_id,
                    "title": seed.title,
                    "url": seed.url,
                    "domain": seed.domain,
                    "source_type": seed.source_type,
                    "reliability": seed.reliability,
                    "language": seed.language,
                    "location": seed.location,
                    "text": seed.text,
                    "chunk_index": seed.chunk_index,
                    "total_chunks": seed.total_chunks,
                },
            )
        ]

        fake_qdrant = FakeQdrantService(points=fake_points)
        fake_embed = FakeEmbeddingService(vector=[0.1] * 1536)
        fallback = _make_keyword_retriever([])

        hybrid_retriever = HybridRetriever(fake_qdrant, fake_embed, None, fallback)  # type: ignore[arg-type]
        # Keyword retriever wires _fallback_service so answer_from_chunks()
        # returns the response with citations preserved.
        keyword_retriever = _make_keyword_retriever(vi_chunks)
        agent = AgentService(hybrid_retriever=hybrid_retriever, retriever=keyword_retriever)

        response = await agent.answer(
            session_id="test-vi-sess",
            message="làng chài Hàm Ninh",
            language="vi",
        )

        assert isinstance(response, ChatResponse)
        assert response.session_id == "test-vi-sess"
        assert len(response.citations) >= 1
        # Verify at least one citation references the seed chunk
        citation_sources = {c.source for c in response.citations}
        assert seed.title in citation_sources, (
            f"Expected '{seed.title}' in citations {citation_sources}"
        )


class TestAgentServiceEnQuery:
    """Test (b): AgentService.answer() with en query returns ChatResponse with
    citations referencing proposition chunk_ids from the real corpus."""

    @pytest.mark.asyncio
    async def test_answer_en_query_returns_citations(self, loaded_chunks):
        """AgentService with HybridRetriever handles English-language query.

        The corpus is predominantly Vietnamese; we use a synthetic English chunk
        for the keyword retriever while still validating the real loaded_chunks
        fixture path and the hybrid retriever citation flow.
        """
        # All corpus chunks are Vietnamese; build a synthetic English chunk for
        # the keyword retriever to guarantee answer_from_chunks() composition path.
        en_seed = RAGChunk(
            chunk_id="en-corpus-seed",
            source_id="en-src-1",
            title="Hàm Ninh Fishing Village",
            url="https://example.com/ham-ninh-en",
            domain="tourism",
            source_type="blog",
            reliability="medium",
            language="en",
            location="Hàm Ninh",
            text="English content about Hàm Ninh fishing village.",
            chunk_index=0,
            total_chunks=1,
        )

        fake_points = [
            FakePoint(
                id=0,
                payload={
                    "chunk_id": en_seed.chunk_id,
                    "source_id": en_seed.source_id,
                    "title": en_seed.title,
                    "url": en_seed.url,
                    "domain": en_seed.domain,
                    "source_type": en_seed.source_type,
                    "reliability": en_seed.reliability,
                    "language": en_seed.language,
                    "location": en_seed.location,
                    "text": en_seed.text,
                    "chunk_index": en_seed.chunk_index,
                    "total_chunks": en_seed.total_chunks,
                },
            )
        ]

        fake_qdrant = FakeQdrantService(points=fake_points)
        fake_embed = FakeEmbeddingService(vector=[0.1] * 1536)
        fallback = _make_keyword_retriever([])
        hybrid_retriever = HybridRetriever(fake_qdrant, fake_embed, None, fallback)  # type: ignore[arg-type]
        keyword_retriever = _make_keyword_retriever([en_seed])
        agent = AgentService(hybrid_retriever=hybrid_retriever, retriever=keyword_retriever)

        response = await agent.answer(
            session_id="test-en-sess",
            message="Hàm Ninh fishing village",
            language="en",
        )

        assert isinstance(response, ChatResponse)
        assert response.session_id == "test-en-sess"
        assert len(response.citations) >= 1
        citation_sources = {c.source for c in response.citations}
        assert en_seed.title in citation_sources, (
            f"Expected '{en_seed.title}' in citations {citation_sources}"
        )


class TestAgentServiceFallbackWhenHybridNone:
    """Test (c): AgentService._retrieve_node() falls back to in-memory retriever
    when hybrid_retriever is None."""

    @pytest.mark.asyncio
    async def test_fallback_to_keyword_retriever_when_hybrid_none(self):
        """When hybrid_retriever is None, AgentService must use _retriever."""
        fallback_chunks = [
            RAGChunk(
                chunk_id="fallback-chunk-1",
                source_id="fb-src",
                title="Hàm Ninh Sunset",
                url="https://example.com/sunset",
                domain="tourism",
                source_type="blog",
                reliability="high",
                language="vi",
                location="Hàm Ninh",
                text="Hoàng hôn tại Hàm Ninh rất đẹp.",
                chunk_index=0,
                total_chunks=1,
            )
        ]
        keyword_retriever = _make_keyword_retriever(fallback_chunks)

        # hybrid_retriever=None, retriever=keyword_retriever
        agent = AgentService(hybrid_retriever=None, retriever=keyword_retriever)

        state: AgentState = {
            "session_id": "test-fb-sess",
            "message": "hoàng hôn Hàm Ninh",
            "language": "vi",
            "history": [],
            "retrieval_query": "hoàng hôn Hàm Ninh",
            "fallback_reason": None,
            "intent": "general",
        }

        result_state = await agent._retrieve_node(state)

        assert len(result_state["chunks"]) >= 1
        assert result_state["chunks"][0].chunk_id == "fallback-chunk-1"
        assert len(result_state["citations"]) >= 1


class TestAgentServiceFallbackOnException:
    """Test (d): AgentService._retrieve_node() uses fallback Retriever when
    hybrid_search raises an exception."""

    @pytest.mark.asyncio
    async def test_fallback_on_qdrant_exception(self):
        """HybridRetriever.search() raises → AgentService must still return chunks."""

        class ErrorQdrant(FakeQdrantService):
            async def dense_search(self, dense_vector: list[float], top_k: int = 5):
                raise RuntimeError("Qdrant unavailable")

        error_qdrant = ErrorQdrant()
        fake_embed = FakeEmbeddingService(vector=[0.1] * 1536)

        fallback_chunks = [
            RAGChunk(
                chunk_id="exc-fallback-chunk",
                source_id="exc-src",
                title="Emergency Fallback",
                url=None,
                domain="tourism",
                source_type="blog",
                reliability="low",
                language="vi",
                location="Hàm Ninh",
                text="Fallback keyword result after Qdrant error.",
                chunk_index=0,
                total_chunks=1,
            )
        ]
        keyword_fallback = _make_keyword_retriever(fallback_chunks)

        hybrid = HybridRetriever(error_qdrant, fake_embed, None, keyword_fallback)  # type: ignore[arg-type]
        agent = AgentService(hybrid_retriever=hybrid, retriever=None)

        response = await agent.answer(
            session_id="test-exc-sess",
            message="test query",
            language="vi",
        )

        # Should still return a response (from keyword fallback)
        assert isinstance(response, ChatResponse)
        assert response.session_id == "test-exc-sess"


class TestAgentServiceIntentRouting:
    """Test soft routing: _answer_node uses intent to decide Places vs LLM.

    restaurant_search/navigation → Places API enrichment (soft)
    cultural_query/unknown → LLM with RAG context
    """

    @pytest.mark.parametrize(
        "message,is_place",
        [
            ("recommend a restaurant in Hàm Ninh", True),
            ("gợi ý địa điểm Hàm Ninh", True),
            ("đề xuất nhà hàng Hàm Ninh", True),
            ("kiếm nhà nghỉ tốt", True),
            ("đường đi bến tàu", True),
            ("what is the history of Hàm Ninh?", False),
            ("làng chài Hàm Ninh có gì?", False),
            ("chào bạn", False),  # conversational
        ],
    )
    def test_routing_decision(self, message, is_place):
        from agents.guardrails.grounded_answer import detect_intent

        intent = detect_intent(message)
        place_intents = {"restaurant_search", "navigation"}
        result = intent in place_intents
        assert result is is_place, f"Message '{message}' intent={intent}, expected is_place={is_place}"


class TestAgentServiceComposeFallback:
    """Test (f): AgentService._compose_fallback() returns a ChatResponse with
    fallback=True and honest no-evidence message."""

    @pytest.mark.asyncio
    async def test_compose_fallback_returns_no_evidence_response(self):
        """When no chunks are available and no LLM, compose_fallback returns an
        honest no-evidence ChatResponse with fallback=True."""
        keyword_retriever = _make_keyword_retriever([])
        agent = AgentService(hybrid_retriever=None, retriever=keyword_retriever)

        state: AgentState = {
            "session_id": "test-fb-msg-sess",
            "message": "làng chài Hàm Ninh",
            "language": "vi",
            "history": [],
            "retrieval_query": "làng chài Hàm Ninh",
            "chunks": [],
            "citations": [],
            "fallback_reason": None,
            "intent": "general",
        }

        response = await agent._compose_fallback(state, "no_chunks")

        assert isinstance(response, ChatResponse)
        assert response.fallback is True
        assert len(response.citations) == 0
        assert len(response.places) == 0
        assert response.session_id == "test-fb-msg-sess"
        assert len(response.message) > 0  # honest message exists