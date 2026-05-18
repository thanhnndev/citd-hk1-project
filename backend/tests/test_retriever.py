"""Tests for the deterministic keyword retriever."""

import pytest

from app.models.rag import RAGChunk
from app.models.response import Citation
from app.services.retriever import (
    RELIABILITY_BOOST,
    Retriever,
    citation_from_chunk,
    _tokenize,
)


def _make_chunk(**overrides) -> RAGChunk:
    """Factory for RAGChunk with sensible defaults."""
    defaults = dict(
        chunk_id="abc123",
        source_id="doc-1",
        title="Test Document",
        url="https://example.com/test",
        domain="example.com",
        source_type="blog",
        reliability="medium",
        language="vi",
        location="Phú Quốc",
        text="Hello world this is a test document about tourism",
        chunk_index=0,
        total_chunks=1,
    )
    defaults.update(overrides)
    return RAGChunk(**defaults)


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_simple_english(self):
        assert _tokenize("Hello World") == ["hello", "world"]

    def test_vietnamese(self):
        tokens = _tokenize("làng chài Hàm Ninh")
        assert "làng" in tokens
        assert "chài" in tokens
        assert "hàm" in tokens
        assert "ninh" in tokens

    def test_punctuation_stripped(self):
        assert _tokenize("hello, world!") == ["hello", "world"]

    def test_empty_string(self):
        assert _tokenize("") == []

    def test_mixed_case(self):
        assert _tokenize("HELLO hello Hello") == ["hello", "hello", "hello"]


# ---------------------------------------------------------------------------
# Citation mapping
# ---------------------------------------------------------------------------


class TestCitationFromChunk:
    def test_basic_mapping(self):
        chunk = _make_chunk(
            title="My Source",
            url="https://example.com/doc",
            text="This is the text content that should be truncated or not.",
        )
        citation = citation_from_chunk(chunk)
        assert isinstance(citation, Citation)
        assert citation.source == "My Source"
        assert citation.url == "https://example.com/doc"

    def test_snippet_truncated_at_200(self):
        long_text = "A" * 300
        chunk = _make_chunk(text=long_text)
        citation = citation_from_chunk(chunk)
        assert len(citation.snippet) == 200
        assert citation.snippet == "A" * 200

    def test_snippet_short_text(self):
        chunk = _make_chunk(text="short")
        citation = citation_from_chunk(chunk)
        assert citation.snippet == "short"

    def test_none_url(self):
        chunk = _make_chunk(url=None)
        citation = citation_from_chunk(chunk)
        assert citation.url is None


# ---------------------------------------------------------------------------
# Retriever — basic search
# ---------------------------------------------------------------------------


class TestRetrieverBasic:
    def _corpus(self) -> list[RAGChunk]:
        return [
            _make_chunk(
                chunk_id="c1", source_id="d1", text="làng chài Hàm Ninh fishing village",
            ),
            _make_chunk(
                chunk_id="c2", source_id="d2", text="Phú Quốc beach resort luxury hotel",
            ),
            _make_chunk(
                chunk_id="c3", source_id="d3", text="Hàm Ninh seafood restaurant ghẹ luộc",
            ),
        ]

    def test_returns_results_for_matching_query(self):
        retriever = Retriever(self._corpus())
        result = retriever.search("làng chài")
        assert result.total_found >= 1
        assert len(result.chunks) >= 1

    def test_no_results_for_unmatched_query(self):
        retriever = Retriever(self._corpus())
        result = retriever.search("xyznonexistent")
        assert result.total_found == 0
        assert result.chunks == []

    def test_respects_top_k(self):
        retriever = Retriever(self._corpus())
        result = retriever.search("Hàm Ninh", top_k=1)
        assert len(result.chunks) == 1

    def test_empty_query(self):
        retriever = Retriever(self._corpus())
        result = retriever.search("")
        assert result.total_found == 0
        assert result.latency_ms >= 0

    def test_latency_measured(self):
        retriever = Retriever(self._corpus())
        result = retriever.search("làng chài")
        assert result.latency_ms >= 0
        assert result.latency_ms < 1000  # sanity: sub-second


# ---------------------------------------------------------------------------
# Retriever — scoring
# ---------------------------------------------------------------------------


class TestRetrieverScoring:
    def test_reliability_boost_high(self):
        """High-reliability chunks rank above equal-text medium-reliability."""
        corpus = [
            _make_chunk(
                chunk_id="c1", source_id="d1", reliability="high",
                text="Hàm Ninh beautiful fishing village",
            ),
            _make_chunk(
                chunk_id="c2", source_id="d2", reliability="medium",
                text="Hàm Ninh beautiful fishing village",
            ),
        ]
        retriever = Retriever(corpus)
        result = retriever.search("Hàm Ninh", top_k=2)
        assert result.chunks[0].reliability == "high"
        assert result.chunks[1].reliability == "medium"

    def test_tf_weighting(self):
        """Chunks with more query-token occurrences score higher."""
        corpus = [
            _make_chunk(
                chunk_id="c1", source_id="d1",
                text="Hàm Ninh is great",
            ),
            _make_chunk(
                chunk_id="c2", source_id="d2",
                text="Hàm Ninh Hàm Ninh Hàm Ninh is very great Hàm Ninh",
            ),
        ]
        retriever = Retriever(corpus)
        result = retriever.search("Hàm Ninh", top_k=2)
        assert result.chunks[0].chunk_id == "c2"
        assert result.chunks[1].chunk_id == "c1"

    def test_idf_rarer_token_matters_more(self):
        """A token appearing in fewer chunks contributes more per occurrence."""
        corpus = [
            _make_chunk(chunk_id="c1", source_id="d1", text="common common"),
            _make_chunk(chunk_id="c2", source_id="d2", text="common common"),
            _make_chunk(chunk_id="c3", source_id="d3", text="common common"),
            _make_chunk(chunk_id="c4", source_id="d4", text="rare unique42"),
        ]
        retriever = Retriever(corpus)
        # "rare" appears in 1 chunk; "common" appears in 3.
        # IDF("rare") > IDF("common"), so searching "rare" yields
        # a higher per-chunk score than searching "common".
        result_rare = retriever.search("rare")
        result_common = retriever.search("common")
        # The single rare match should score higher than any common match
        assert result_rare.total_found == 1
        assert result_common.total_found == 3
        # Verify IDF math: rarer term has higher per-token contribution
        from app.services.retriever import _idf
        idf_rare = _idf(1, 4)
        idf_common = _idf(3, 4)
        assert idf_rare > idf_common


# ---------------------------------------------------------------------------
# Retriever — determinism
# ---------------------------------------------------------------------------


class TestRetrieverDeterminism:
    def test_same_query_same_order(self):
        corpus = [
            _make_chunk(chunk_id="c1", source_id="d1", text="Hàm Ninh village"),
            _make_chunk(chunk_id="c2", source_id="d2", text="Hàm Ninh beach"),
            _make_chunk(chunk_id="c3", source_id="d3", text="Hàm Ninh seafood restaurant"),
        ]
        retriever = Retriever(corpus)
        r1 = retriever.search("Hàm Ninh", top_k=5)
        r2 = retriever.search("Hàm Ninh", top_k=5)
        assert [c.chunk_id for c in r1.chunks] == [c.chunk_id for c in r2.chunks]

    def test_tie_broken_by_chunk_id(self):
        """Chunks with identical score ordered by chunk_id ascending."""
        corpus = [
            _make_chunk(chunk_id="z99", source_id="d1", text="same text"),
            _make_chunk(chunk_id="a01", source_id="d2", text="same text"),
            _make_chunk(chunk_id="m50", source_id="d3", text="same text"),
        ]
        retriever = Retriever(corpus)
        result = retriever.search("same text", top_k=5)
        ids = [c.chunk_id for c in result.chunks]
        assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# Retriever — tourism corpus integration
# ---------------------------------------------------------------------------


class TestRetrieverTourismCorpus:
    @pytest.fixture(scope="class")
    def retriever(self):
        from app.services.retriever import load_corpus as _load
        chunks = _load("../data/tourism_documents.jsonl")
        return Retriever(chunks)

    def test_làng_chài_hàm_ninh_returns_results(self, retriever):
        result = retriever.search("làng chài Hàm Ninh")
        assert result.total_found >= 1
        assert len(result.chunks) >= 1

    def test_results_include_citations(self, retriever):
        result, citations = retriever.search_with_citations("làng chài Hàm Ninh")
        assert len(citations) == len(result.chunks)
        for c in citations:
            assert isinstance(c, Citation)
            assert c.source is not None

    def test_reliability_boost_applied(self, retriever):
        """High-reliability chunks get a score multiplier (verified via boost constant)."""
        from app.services.retriever import RELIABILITY_BOOST
        assert RELIABILITY_BOOST["high"] > RELIABILITY_BOOST["medium"]
        # Sanity: query returns results at all
        result = retriever.search("làng chài Hàm Ninh", top_k=5)
        assert result.total_found >= 1

    def test_reliability_boost_end_to_end(self):
        """When TF/IDF are identical, high-reliability chunk ranks first."""
        from app.services.retriever import Retriever
        from app.models.rag import RAGChunk
        corpus = [
            RAGChunk(
                chunk_id="c_med", source_id="d1", title="Med", url=None,
                domain="example.com", source_type="blog", reliability="medium",
                language="vi", location="Phú Quốc",
                text="Hàm Ninh làng chài", chunk_index=0, total_chunks=1,
            ),
            RAGChunk(
                chunk_id="c_high", source_id="d2", title="High", url=None,
                domain="example.com", source_type="official", reliability="high",
                language="vi", location="Phú Quốc",
                text="Hàm Ninh làng chài", chunk_index=0, total_chunks=1,
            ),
        ]
        r = Retriever(corpus)
        result = r.search("Hàm Ninh làng chài", top_k=2)
        assert result.chunks[0].reliability == "high"


# ---------------------------------------------------------------------------
# Retriever — edge cases
# ---------------------------------------------------------------------------


class TestRetrieverEdgeCases:
    def test_empty_corpus(self):
        retriever = Retriever([])
        result = retriever.search("anything")
        assert result.total_found == 0
        assert result.chunks == []

    def test_single_chunk_corpus(self):
        retriever = Retriever([_make_chunk(chunk_id="only-one", text="hello")])
        result = retriever.search("hello")
        assert result.total_found == 1
        assert result.chunks[0].chunk_id == "only-one"

    def test_top_k_larger_than_results(self):
        retriever = Retriever([_make_chunk(chunk_id="c1", text="one match")])
        result = retriever.search("one", top_k=100)
        assert len(result.chunks) == 1

    def test_query_tokens_none_match(self):
        corpus = [
            _make_chunk(chunk_id="c1", text="only vietnamese text here"),
        ]
        retriever = Retriever(corpus)
        result = retriever.search("xyz abc")
        assert result.total_found == 0

    def test_unknown_reliability_defaults_to_1x(self):
        chunk = _make_chunk(chunk_id="c1", reliability="platinum", text="test")
        retriever = Retriever([chunk])
        result = retriever.search("test")
        assert result.total_found == 1  # doesn't crash
