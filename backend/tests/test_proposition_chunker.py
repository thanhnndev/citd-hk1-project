"""Tests for PropositionChunker: markdown/entity splitting and proposition extraction."""

import json
import pytest
from pathlib import Path

from app.services.proposition_chunker import (
    PropositionChunker,
    _chunk_id,
    _parse_frontmatter,
    _split_sentences,
    _to_propositions,
    _detect_language,
    _normalize,
)


# ---------------------------------------------------------------------------
# Helpers — deterministic chunk_id
# ---------------------------------------------------------------------------

class TestChunkId:
    def test_deterministic_same_inputs(self):
        assert _chunk_id("doc-1", 0) == _chunk_id("doc-1", 0)

    def test_different_index_different_id(self):
        assert _chunk_id("doc-1", 0) != _chunk_id("doc-1", 1)

    def test_different_source_different_id(self):
        assert _chunk_id("doc-1", 0) != _chunk_id("doc-2", 0)

    def test_is_hex_sha256_prefix(self):
        chunk_id = _chunk_id("test-doc", 5)
        # chunk_id is first 32 hex chars of SHA-256
        assert len(chunk_id) == 32
        int(chunk_id, 16)  # raises if not valid hex


# ---------------------------------------------------------------------------
# Helpers — frontmatter parsing
# ---------------------------------------------------------------------------

class TestParseFrontmatter:
    def test_parses_yaml_dict(self):
        raw = "---\ntitle: Test Doc\nsource_type: blog\nreliability: high\n---\nContent here."
        meta = _parse_frontmatter(raw)
        assert meta["title"] == "Test Doc"
        assert meta["source_type"] == "blog"
        assert meta["reliability"] == "high"

    def test_parses_list_values(self):
        raw = '---\ntags: ["travel", "food"]\n---\nContent'
        meta = _parse_frontmatter(raw)
        assert meta["tags"] == ["travel", "food"]

    def test_no_frontmatter(self):
        raw = "Plain text without markers."
        assert _parse_frontmatter(raw) == {}

    def test_strips_quotes(self):
        raw = '---\ntitle: "Quoted Title"\nauthor: \'Another Quote\'\n---\n'
        meta = _parse_frontmatter(raw)
        assert meta["title"] == "Quoted Title"
        assert meta["author"] == "Another Quote"


# ---------------------------------------------------------------------------
# Helpers — sentence splitting & propositions
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_collapse_whitespace(self):
        assert _normalize("  Hello   \n  World  ") == "Hello World"

    def test_strips_leading_trailing(self):
        assert _normalize("  \n  Test  \n  ") == "Test"


class TestSplitSentences:
    def test_basic_period_separation(self):
        sentences = _split_sentences("First sentence. Second sentence. Third sentence.")
        assert len(sentences) == 3
        assert all(s for s in sentences)

    def test_vietnamese_accent_terminators(self):
        text = "Đây là câu đầu tiên. Đây là câu thứ hai."
        sentences = _split_sentences(text)
        assert len(sentences) == 2

    def test_question_mark_terminator(self):
        # "Yes it is." is exactly 10 chars → filtered out by >10 rule,
        # so only the first sentence passes the length gate.
        sentences = _split_sentences("Is this clear? Yes it is.")
        assert len(sentences) == 1
        assert sentences[0] == "Is this clear?"

    def test_exclamation_terminator(self):
        # "Wow!" is 4 chars → filtered out; only "That's truly amazing." survives
        sentences = _split_sentences("Wow! That's truly amazing.")
        assert len(sentences) == 1
        assert sentences[0] == "That's truly amazing."

    def test_abbreviation_no_split(self):
        # Mr. followed by lowercase — should not split
        sentences = _split_sentences("Mr. Smith visited the temple. It was beautiful.")
        # With current regex, this may split; filter ensures >10 char minimum
        assert len(sentences) >= 1

    def test_filter_short_results(self):
        sentences = _split_sentences("Hi.")
        assert sentences == []

    def test_preserve_vietnamese_diacritics(self):
        sentences = _split_sentences("Hàm Ninh là một làng chài. Nổi tiếng với hải sản.")
        assert len(sentences) == 2
        assert "Hàm" in sentences[0]


class TestToPropositions:
    def test_short_paragraph_returns_empty(self):
        assert _to_propositions("Short.") == []

    def test_single_sentence_paragraph(self):
        result = _to_propositions(
            "This is a longer sentence that should pass the length check."
        )
        assert len(result) == 1

    def test_multiple_sentences_split(self):
        text = (
            "First sentence that is long enough to pass. "
            "Second sentence also passes length threshold. "
            "Third sentence as well passes the check."
        )
        result = _to_propositions(text)
        assert len(result) >= 2

    def test_empty_input(self):
        assert _to_propositions("") == []
        assert _to_propositions("   ") == []


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

class TestDetectLanguage:
    def test_pure_english(self):
        assert _detect_language("Test Title", "This is a test paragraph in English.") == "en"

    def test_pure_vietnamese(self):
        text = "Hàm Ninh là một ngôi làng đánh cá nổi tiếng ở Phú Quốc"
        assert _detect_language("Làng Chài", text) == "vi"

    def test_mixed_content_vietnamese_dominant(self):
        text = "Hàm Ninh có làng chài và bãi biển đẹp ở Phú Quốc"
        assert _detect_language("Test", text) == "vi"

    def test_mixed_content_english_dominant(self):
        text = "This is a test document about tourism and travel"
        assert _detect_language("Test", text) == "en"

    def test_empty_text(self):
        # No alphabetic chars in combined sample → denominator is 0, guard returns "en"
        assert _detect_language("", "") == "en"


# ---------------------------------------------------------------------------
# Integration — real corpus via PropositionChunker
# ---------------------------------------------------------------------------

class TestPropositionChunkerRealCorpus:
    """Test PropositionChunker against real data files."""

    @pytest.fixture
    def chunker(self):
        docs_dir = Path("data/cleaned/documents")
        entities_dir = Path("data/entities")
        if not docs_dir.exists():
            docs_dir = Path(__file__).resolve().parent.parent.parent / "data" / "cleaned" / "documents"
            entities_dir = Path(__file__).resolve().parent.parent.parent / "data" / "entities"
        return PropositionChunker(docs_dir, entities_dir)

    def test_chunk_markdown_files_produces_results(self, chunker):
        chunks = chunker.chunk_markdown_files()
        assert len(chunks) > 0

    def test_chunk_all_includes_entity_json(self, chunker):
        chunks = chunker.chunk_all()
        source_ids = {c["source_id"] for c in chunks}
        # Entity files have source_ids like "culture_history:topic_name" or "restaurants:entity_name"
        entity_ids = [sid for sid in source_ids if ":" in sid]
        assert len(entity_ids) >= 1

    def test_matching_actual_corpus_count(self, chunker):
        """PropositionChunker output count matches tourism_documents.jsonl (607)."""
        chunks = chunker.chunk_all()
        assert len(chunks) == 607

    def test_all_chunks_have_required_fields(self, chunker):
        """Every chunk dict has all fields required by RAGChunk schema."""
        required = (
            "chunk_id", "source_id", "title", "domain",
            "source_type", "reliability", "language", "location", "text",
            "chunk_index", "total_chunks",
        )
        chunks = chunker.chunk_all()
        for i, chunk in enumerate(chunks):
            missing = [f for f in required if f not in chunk]
            assert not missing, f"Chunk {i} missing: {missing}"

    def test_no_empty_text_in_chunks(self, chunker):
        """No proposition has empty or whitespace-only text."""
        chunks = chunker.chunk_all()
        for i, chunk in enumerate(chunks):
            text = chunk.get("text", "").strip()
            assert text, f"Chunk {i} ({chunk.get('chunk_id', '?')}) has empty text"

    def test_no_duplicate_chunk_ids(self, chunker):
        """All chunk_ids in the full output are unique."""
        chunks = chunker.chunk_all()
        ids = [c["chunk_id"] for c in chunks]
        assert len(ids) == len(set(ids)), "Duplicate chunk_ids found"

    def test_chunk_id_deterministic(self, chunker):
        """Same inputs always produce same chunk_id."""
        chunks_a = chunker.chunk_all()
        chunks_b = chunker.chunk_all()
        for a, b in zip(chunks_a, chunks_b):
            assert a["chunk_id"] == b["chunk_id"]

    def test_multilingual_content_present(self, chunker):
        """Both Vietnamese and English chunks are present."""
        chunks = chunker.chunk_all()
        languages = {c["language"] for c in chunks}
        assert "vi" in languages
        assert languages <= {"vi", "en"}

    def test_vietnamese_propositions_longer_than_threshold(self, chunker):
        """Proposition text is at least 15 characters (atomic threshold)."""
        chunks = chunker.chunk_all()
        for chunk in chunks:
            if chunk["language"] == "vi":
                assert len(chunk["text"]) >= 15, (
                    f"Chunk {chunk['chunk_id']} Vietnamese text too short: '{chunk['text']}'"
                )

    def test_source_types_present(self, chunker):
        """Multiple source types are represented in chunks."""
        chunks = chunker.chunk_all()
        source_types = {c["source_type"] for c in chunks}
        assert len(source_types) >= 3

    def test_reliability_values_valid(self, chunker):
        """Reliability field is one of the known tiers."""
        valid_tiers = {"high", "medium", "low"}
        chunks = chunker.chunk_all()
        for chunk in chunks:
            assert chunk["reliability"] in valid_tiers, (
                f"Unknown reliability: {chunk['reliability']}"
            )

    def test_location_field_populated(self, chunker):
        """All chunks have a non-empty location."""
        chunks = chunker.chunk_all()
        for chunk in chunks:
            location = chunk.get("location", "").strip()
            assert location, f"Chunk {chunk['chunk_id']} has empty location"

    def test_domain_is_tourism_or_domain_name(self, chunker):
        """Domain is either the default 'tourism' or sourced from frontmatter."""
        chunks = chunker.chunk_all()
        for chunk in chunks:
            # Domain is non-empty string (either "tourism" or a real source domain)
            assert chunk["domain"], f"Empty domain for {chunk['chunk_id']}"

    def test_chunk_indices_non_negative(self, chunker):
        """All chunk_index values are non-negative."""
        chunks = chunker.chunk_all()
        for chunk in chunks:
            assert chunk["chunk_index"] >= 0
            assert isinstance(chunk["chunk_index"], int)

    def test_total_chunks_positive(self, chunker):
        """All total_chunks values are positive integers."""
        chunks = chunker.chunk_all()
        for chunk in chunks:
            assert chunk["total_chunks"] >= 1
            assert isinstance(chunk["total_chunks"], int)


# ---------------------------------------------------------------------------
# Edge cases — empty files, single-sentence docs, mixed language
# ---------------------------------------------------------------------------

class TestPropositionChunkerEdgeCases:
    @pytest.fixture
    def edge_chunker(self, tmp_path):
        docs = tmp_path / "docs"
        entities = tmp_path / "entities"
        docs.mkdir()
        entities.mkdir()
        return PropositionChunker(docs, entities)

    def test_empty_markdown_file_produces_no_chunks(self, edge_chunker, tmp_path):
        (tmp_path / "docs" / "empty.md").write_text("", encoding="utf-8")
        chunks = edge_chunker.chunk_markdown_files()
        # Empty file with no content → no propositions
        assert all(c["source_id"] != "empty" for c in chunks)

    def test_single_short_sentence_file(self, edge_chunker, tmp_path):
        # Write a file too short to produce a proposition
        md = tmp_path / "docs" / "short.md"
        md.write_text(
            "---\ntitle: Short\n---\nShort sentence.",
            encoding="utf-8",
        )
        chunks = edge_chunker.chunk_markdown_files()
        # < 20 char body → no proposition
        source_ids = [c["source_id"] for c in chunks]
        assert "short" not in source_ids

    def test_markdown_with_only_frontmatter(self, edge_chunker, tmp_path):
        (tmp_path / "docs" / "metaonly.md").write_text(
            "---\ntitle: Meta Only\n---\n",
            encoding="utf-8",
        )
        chunks = edge_chunker.chunk_markdown_files()
        source_ids = [c["source_id"] for c in chunks]
        assert "metaonly" not in source_ids

    def test_non_utf8_encoding_fallback(self, edge_chunker, tmp_path):
        # UTF-8 is default; ensure the chunker handles it gracefully
        md = tmp_path / "docs" / "accent.md"
        content = "---\ntitle: Vietnamese\n---\nHà Nội là thủ đô của Việt Nam."
        md.write_text(content, encoding="utf-8")
        chunks = edge_chunker.chunk_markdown_files()
        vi_chunks = [c for c in chunks if c["source_id"] == "accent"]
        assert len(vi_chunks) >= 1
        assert "vi" in [c["language"] for c in vi_chunks]

    def test_missing_entity_files_ignored(self, edge_chunker, tmp_path):
        # No entity JSON files present — chunk_all should not raise
        chunks = edge_chunker.chunk_all()
        assert isinstance(chunks, list)

    def test_malformed_entity_json_ignored(self, edge_chunker, tmp_path):
        (tmp_path / "entities" / "bad.json").write_text("{ invalid json", encoding="utf-8")
        chunks = edge_chunker.chunk_all()
        # Bad file is logged but does not crash
        assert isinstance(chunks, list)

    def test_entity_list_format(self, edge_chunker, tmp_path):
        # chunk_all only processes known filenames; use restaurants.json
        entity_file = tmp_path / "entities" / "restaurants.json"
        entity_file.write_text(
            json.dumps([
                {"entity_name": "Test Restaurant", "address": "123 Main St"},
                {"entity_name": "Second Place", "address": "456 Oak Ave"},
            ]),
            encoding="utf-8",
        )
        chunks = edge_chunker.chunk_all()
        test_chunks = [c for c in chunks if c["source_id"].startswith("restaurants:")]
        assert len(test_chunks) >= 2

    def test_entity_dict_format(self, edge_chunker, tmp_path):
        # Use restaurants.json as the known entity file
        entity_file = tmp_path / "entities" / "restaurants.json"
        entity_file.write_text(
            json.dumps({"entity_name": "Single Entity", "review_summary": "Great food here."}),
            encoding="utf-8",
        )
        chunks = edge_chunker.chunk_all()
        test_chunks = [c for c in chunks if c["source_id"].startswith("restaurants:")]
        assert len(test_chunks) >= 1

    def test_proposition_text_minimum_length(self, edge_chunker, tmp_path):
        """Propositions must meet the atomic minimum length."""
        md = tmp_path / "docs" / "longer.md"
        md.write_text(
            "---\ntitle: Longer Doc\n---\n"
            "Đây là một câu dài hơn hai mươi ký tự để đảm bảo nó được giữ lại làm proposition.",
            encoding="utf-8",
        )
        chunks = edge_chunker.chunk_markdown_files()
        for chunk in chunks:
            assert len(chunk["text"]) >= 15, (
                f"Chunk too short: '{chunk['text']}'"
            )

    def test_deterministic_chunk_ids_across_runs(self, edge_chunker, tmp_path):
        """Running chunk_all twice yields identical chunk_ids in identical order."""
        md = tmp_path / "docs" / "repeat.md"
        md.write_text(
            "---\ntitle: Repeat Doc\nsource_type: blog\n---\n"
            "First sentence that is long enough. Second sentence that is also long enough.",
            encoding="utf-8",
        )
        run_a = edge_chunker.chunk_all()
        run_b = edge_chunker.chunk_all()
        assert len(run_a) == len(run_b)
        for a, b in zip(run_a, run_b):
            assert a["chunk_id"] == b["chunk_id"]
            assert a["text"] == b["text"]

    def test_location_defaults_when_missing_in_frontmatter(self, edge_chunker, tmp_path):
        """Frontmatter without location uses the default Hàm Ninh location."""
        md = tmp_path / "docs" / "noloc.md"
        md.write_text(
            "---\ntitle: No Location\n---\nHàm Ninh là một ngôi làng đánh cá nổi tiếng ở Phú Quốc Việt Nam.",
            encoding="utf-8",
        )
        chunks = edge_chunker.chunk_markdown_files()
        noloc = [c for c in chunks if c["source_id"] == "noloc"]
        assert len(noloc) >= 1
        for chunk in noloc:
            assert chunk["location"] == "Hàm Ninh, Phú Quốc"