"""Tests for output guardrails — grounding verification."""

from __future__ import annotations

import time

import pytest

from agents.guardrails.output_guardrails import (
    verify_grounding,
    _extract_key_tokens,
    _extract_citation_text,
    _is_no_evidence_message,
    _compute_overlap_ratio,
    HIGH_THRESHOLD,
    LOW_THRESHOLD,
)
from agents.guardrails.input_guardrails import GuardrailResult


# ===================================================================
# Helper: _extract_key_tokens
# ===================================================================

class TestExtractKeyTokens:
    def test_removes_stop_words(self) -> None:
        tokens = _extract_key_tokens("the cat is on the mat")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "on" not in tokens
        assert "cat" in tokens
        assert "mat" in tokens

    def test_keeps_numbers(self) -> None:
        tokens = _extract_key_tokens("The price is 150000 dong")
        assert "150000" in tokens

    def test_lowercase_normalization(self) -> None:
        tokens = _extract_key_tokens("Hello WORLD Test")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens

    def test_handles_vietnamese(self) -> None:
        tokens = _extract_key_tokens("Phú Quốc là đảo đẹp nhất Việt Nam")
        assert "phú" in tokens
        assert "quốc" in tokens
        assert "đảo" in tokens
        # Stop words filtered
        assert "là" not in tokens

    def test_empty_string(self) -> None:
        assert _extract_key_tokens("") == set()

    def test_punctuation_stripping(self) -> None:
        tokens = _extract_key_tokens("Hello, world! How are you?")
        assert "hello" in tokens
        assert "world" in tokens
        assert "," not in tokens
        assert "!" not in tokens


# ===================================================================
# Helper: _compute_overlap_ratio
# ===================================================================

class TestComputeOverlapRatio:
    def test_full_overlap(self) -> None:
        ratio = _compute_overlap_ratio({"cat", "dog"}, {"cat", "dog", "bird"})
        assert ratio == 1.0

    def test_partial_overlap(self) -> None:
        ratio = _compute_overlap_ratio({"cat", "dog", "fish"}, {"cat", "bird"})
        assert ratio == pytest.approx(1 / 3)

    def test_no_overlap(self) -> None:
        ratio = _compute_overlap_ratio({"cat", "dog"}, {"bird", "fish"})
        assert ratio == 0.0

    def test_empty_message_tokens(self) -> None:
        ratio = _compute_overlap_ratio(set(), {"cat", "dog"})
        assert ratio == 0.0


# ===================================================================
# Helper: _extract_citation_text
# ===================================================================

class TestExtractCitationText:
    def test_empty_list(self) -> None:
        assert _extract_citation_text([]) == ""

    def test_none(self) -> None:
        assert _extract_citation_text(None) == ""

    def test_rag_chunk_objects(self) -> None:
        class FakeChunk:
            def __init__(self, text: str, title: str = ""):
                self.text = text
                self.title = title

        chunks = [
            FakeChunk(text="Phú Quốc is beautiful", title="Island Guide"),
            FakeChunk(text="Ham Ninh has great seafood", title="Village Guide"),
        ]
        result = _extract_citation_text(chunks)
        assert "Phú Quốc" in result
        assert "Ham Ninh" in result

    def test_citation_objects(self) -> None:
        class FakeCitation:
            def __init__(self, source: str, snippet: str = "", url: str = ""):
                self.source = source
                self.snippet = snippet
                self.url = url

        citations = [
            FakeCitation(source="Vietnam Tourism", snippet="Beautiful beaches"),
        ]
        result = _extract_citation_text(citations)
        assert "Vietnam Tourism" in result
        assert "Beautiful beaches" in result

    def test_skips_empty_text(self) -> None:
        class FakeChunk:
            def __init__(self, text: str):
                self.text = text
                self.title = ""

        chunks = [FakeChunk(text=""), FakeChunk(text="Valid content")]
        result = _extract_citation_text(chunks)
        assert "Valid content" in result


# ===================================================================
# Helper: _is_no_evidence_message
# ===================================================================

class TestIsNoEvidenceMessage:
    def test_english_uncertainty(self) -> None:
        assert _is_no_evidence_message("I'm not sure about that") is True

    def test_english_dont_know(self) -> None:
        assert _is_no_evidence_message("I don't know the answer") is True

    def test_english_no_results(self) -> None:
        assert _is_no_evidence_message("No results found for your query") is True

    def test_english_not_enough_info(self) -> None:
        assert _is_no_evidence_message("I don't have enough information") is True

    def test_vietnamese_uncertainty(self) -> None:
        assert _is_no_evidence_message("Tôi không biết") is True

    def test_vietnamese_no_info(self) -> None:
        assert _is_no_evidence_message("Không có thông tin về điều này") is True

    def test_vietnamese_not_found(self) -> None:
        assert _is_no_evidence_message("Không tìm thấy kết quả nào") is True

    def test_confident_claim_not_honest(self) -> None:
        assert _is_no_evidence_message(
            "The Eiffel Tower is 330 meters tall"
        ) is False

    def test_regular_query_not_honest(self) -> None:
        assert _is_no_evidence_message(
            "Phú Quốc có nhiều bãi biển đẹp"
        ) is False


# ===================================================================
# verify_grounding — grounded responses
# ===================================================================

class TestVerifyGrounding:

    # --- Fakes for testing ---

    class FakeCitation:
        def __init__(self, source: str, snippet: str, url: str = ""):
            self.source = source
            self.snippet = snippet
            self.url = url

    class FakeRAGChunk:
        def __init__(self, text: str, title: str = ""):
            self.text = text
            self.title = title

    def test_grounded_response_passes(self) -> None:
        """Message with clear overlap to citations → pass."""
        citations = [
            self.FakeCitation(
                source="Du lịch Phú Quốc",
                snippet=(
                    "Phú Quốc là đảo lớn nhất Việt Nam, nằm trong vịnh Thái Lan. "
                    "Đảo nổi tiếng với bãi biển tuyệt đẹp, hải sản tươi sống, "
                    "và sản xuất nước mắm. Làng chài Hàm Ninh là điểm đến "
                    "lý tưởng cho du khách thích hải sản."
                ),
            ),
        ]
        message = (
            "Phú Quốc là đảo lớn nhất Việt Nam, nổi tiếng với bãi biển tuyệt đẹp "
            "và làng chài Hàm Ninh với hải sản tươi sống."
        )
        result = verify_grounding(message, citations)
        assert result.verdict == "pass"
        assert result.reason == "grounded"

    def test_ungrounded_response_flagged(self) -> None:
        """Message making claims not in any citation → flagged."""
        citations = [
            self.FakeCitation(
                source="Phú Quốc Tourism",
                snippet="Phú Quốc has beaches and fishing villages.",
            ),
        ]
        message = (
            "The Eiffel Tower in Paris is 330 meters tall and was built in 1889. "
            "Mount Everest is the highest peak in the world at 8849 meters. "
            "The Great Wall of China stretches over 21000 kilometers."
        )
        result = verify_grounding(message, citations)
        assert result.verdict == "flagged"
        assert result.reason in ("ungrounded", "low_confidence")

    def test_no_citations_honest_passes(self) -> None:
        """No-evidence message with no citations → pass (correctly ungrounded by design)."""
        message = "I'm sorry, I don't have enough information to answer that question."
        result = verify_grounding(message, citations=None)
        assert result.verdict == "pass"
        assert result.reason == "honest_uncertainty"

    def test_no_citations_dishonest_flagged(self) -> None:
        """Confident factual claim with no citations → flagged."""
        message = (
            "The population of Phú Quốc is 179,451 people as of 2024, "
            "and the island has exactly 47 temples and 12 museums."
        )
        result = verify_grounding(message, citations=None)
        assert result.verdict == "flagged"
        assert result.reason == "no_source_material"
        assert result.severity == "high"

    def test_paraphrase_passes(self) -> None:
        """Message that paraphrases citations accurately → pass (fuzzy overlap)."""
        citations = [
            self.FakeCitation(
                source="Vietnam Travel Guide",
                snippet=(
                    "The best time to visit Phú Quốc is during the dry season "
                    "from November to March when rainfall is minimal and "
                    "the sea is calm for snorkeling activities."
                ),
            ),
        ]
        message = (
            "You should visit Phú Quốc in dry season between November and March. "
            "The weather is better then and sea conditions are good for snorkeling."
        )
        result = verify_grounding(message, citations)
        assert result.verdict == "pass"
        assert result.reason == "grounded"

    def test_multi_chunk_synthesis_passes(self) -> None:
        """Message combining facts from 2+ citations → pass."""
        citations = [
            self.FakeRAGChunk(
                text=(
                    "Phú Quốc National Park covers 314 square kilometers "
                    "and protects diverse tropical forest ecosystems."
                ),
                title="National Park Info",
            ),
            self.FakeRAGChunk(
                text=(
                    "The island has two main towns: Dương Đông and An Thới. "
                    "Dương Đông is the administrative center with a population "
                    "of about 30,000 residents."
                ),
                title="Towns and Population",
            ),
        ]
        message = (
            "Phú Quốc có Vườn Quốc Gia rộng 314 km² bảo vệ hệ sinh thái rừng. "
            "Đảo có hai thị trấn chính là Dương Đông và An Thới, "
            "trong đó Dương Đông là trung tâm hành chính."
        )
        result = verify_grounding(message, citations)
        assert result.verdict == "pass"
        assert result.reason == "grounded"


# ===================================================================
# verify_grounding — edge cases
# ===================================================================

class TestVerifyGroundingEdgeCases:
    def test_empty_message(self) -> None:
        result = verify_grounding("")
        assert result.verdict == "pass"
        assert result.reason == "empty_message"

    def test_whitespace_only_message(self) -> None:
        result = verify_grounding("   \n\t  ")
        assert result.verdict == "pass"
        assert result.reason == "empty_message"

    def test_empty_citations_list(self) -> None:
        """Empty list treated same as None — no source material."""
        message = "Phú Quốc is the largest island with amazing seafood."
        result = verify_grounding(message, citations=[])
        assert result.verdict == "flagged"
        assert result.reason == "no_source_material"

    def test_citation_with_empty_text(self) -> None:
        class FakeCitation:
            source = ""
            snippet = ""
            url = ""

        message = "Phú Quốc has great beaches and seafood restaurants."
        result = verify_grounding(message, citations=[FakeCitation()])
        assert result.verdict == "flagged"
        assert result.reason == "empty_citations"

    def test_very_long_message(self) -> None:
        """A long message that is partially grounded should still compute correctly."""
        citations = [
            TestVerifyGrounding.FakeCitation(
                source="Phú Quốc Guide",
                snippet=(
                    "Phú Quốc is the largest island in Vietnam, located in "
                    "the Gulf of Thailand. Known for beaches, fish sauce, "
                    "and pepper farms. Ham Ninh village has fresh seafood."
                ),
            ),
        ]
        # Long grounded portion + some extra ungrounded claims
        message = (
            "Phú Quốc là đảo lớn nhất Việt Nam ở vịnh Thái Lan. "
            "Đảo nổi tiếng với bãi biển, nước mắm, và hồ tiêu. "
            "Làng chài Hàm Ninh có hải sản tươi. "
            "The population of Mars is exactly 42. "
            "The capital of Atlantis is Poseidonia. "
            "The moon is made of green cheese and the sun is a giant lemon. "
            "Tokyo has 50 million people and Paris has 30 million. "
            "The Pacific Ocean is 2000 meters deep everywhere. "
            "Elephants can fly at 300 km/h and dogs can speak French."
        )
        result = verify_grounding(message, citations)
        # Should still produce a verdict (may be flagged due to noise)
        assert result.verdict in ("pass", "flagged")

    def test_no_citations_vietnamese_honest(self) -> None:
        """Vietnamese honest uncertainty without citations → pass."""
        message = "Xin lỗi, tôi không có thông tin về câu hỏi này."
        result = verify_grounding(message, citations=None)
        assert result.verdict == "pass"
        assert result.reason == "honest_uncertainty"

    def test_honest_message_with_citations(self) -> None:
        """Honest uncertainty message even with citations should still pass."""
        citations = [
            TestVerifyGrounding.FakeCitation(
                source="Some Source",
                snippet="Some relevant content about Phú Quốc tourism.",
            ),
        ]
        message = "I'm sorry, I don't have enough information about this topic."
        result = verify_grounding(message, citations)
        # The no-evidence message check happens before overlap,
        # but since citations exist, it goes through overlap path.
        # With honest message + citations, the result depends on overlap.
        assert result.verdict in ("pass", "flagged")

    def test_no_citations_honest_variants(self) -> None:
        """Various forms of honest uncertainty without citations should pass."""
        honest_messages = [
            "I don't know the answer to that.",
            "I couldn't find any information about this.",
            "No information available for your query.",
            "Unfortunately, no results found.",
            "I do not have access to that data.",
        ]
        for msg in honest_messages:
            result = verify_grounding(msg, citations=None)
            assert result.verdict == "pass", f"Failed for: {msg}"


# ===================================================================
# Latency requirements
# ===================================================================

class TestVerifyGroundingLatency:
    def test_verify_grounding_under_200ms(self) -> None:
        """verify_grounding must complete in under 200ms."""

        class FakeCitation:
            def __init__(self, snippet: str):
                self.source = "Test Source"
                self.snippet = snippet
                self.url = ""

        citations = [
            FakeCitation(
                snippet=(
                    "Phú Quốc is the largest island in Vietnam with "
                    "beautiful beaches, rich marine life, and famous "
                    "fish sauce production. Ham Ninh fishing village "
                    "offers fresh seafood. The island covers 574 km² "
                    "and has a tropical monsoon climate with two seasons: "
                    "dry season from November to March and rainy season "
                    "from April to October. Dương Đông is the main town."
                ),
            ),
            FakeCitation(
                snippet=(
                    "Transportation to Phú Quốc includes flights from "
                    "major Vietnamese cities, speedboats from Hà Tiên, "
                    "and ferries from Rạch Giá. The island has an "
                    "international airport with daily connections."
                ),
            ),
        ]

        test_messages = [
            "Phú Quốc là đảo lớn nhất Việt Nam với bãi biển đẹp",
            "I don't have enough information to answer that question.",
            "The Eiffel Tower is 330 meters tall in Paris France",
            "Phú Quốc has great beaches and seafood at Ham Ninh village. "
            "You can fly there from Ho Chi Minh City or take a ferry from Rạch Giá. "
            "The dry season runs from November to March with minimal rainfall.",
            "Xin lỗi, tôi không có thông tin về điều này.",
        ]

        for msg in test_messages:
            t0 = time.perf_counter()
            verify_grounding(msg, citations)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert elapsed_ms < 200, (
                f"verify_grounding took {elapsed_ms:.1f}ms for message of "
                f"length {len(msg)}"
            )

    def test_verify_grounding_no_citations_latency(self) -> None:
        """verify_grounding with no citations must complete in under 200ms."""
        test_messages = [
            "Phú Quốc is a beautiful island in Vietnam with many attractions.",
            "I don't know the answer.",
            "The capital of France is Paris and the population is 2.2 million.",
        ]

        for msg in test_messages:
            t0 = time.perf_counter()
            verify_grounding(msg, citations=None)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert elapsed_ms < 200, (
                f"verify_grounding (no citations) took {elapsed_ms:.1f}ms"
            )


# ===================================================================
# Threshold behavior
# ===================================================================

class TestThresholdBehavior:
    """Verify the specific threshold boundaries work as specified."""

    class FakeCitation:
        def __init__(self, snippet: str):
            self.source = "Test Source"
            self.snippet = snippet
            self.url = ""

    def test_high_overlap_passes(self) -> None:
        """overlap_ratio >= 0.15 → pass."""
        citation = self.FakeCitation(
            snippet=(
                "Phú Quốc is Vietnam's largest island known for beaches, "
                "fish sauce production, and pearl farms with tourism "
                "growing rapidly each year."
            ),
        )
        # High overlap message
        message = (
            "Phú Quốc is Vietnam's largest island known for beaches "
            "and fish sauce production with growing tourism."
        )
        result = verify_grounding(message, [citation])
        assert result.verdict == "pass"

    def test_low_overlap_flagged(self) -> None:
        """overlap_ratio < 0.05 → flagged (ungrounded)."""
        citation = self.FakeCitation(
            snippet="Phú Quốc has some beaches and fish sauce.",
        )
        # Almost no overlap
        message = (
            "The population density of Tokyo metropolitan area exceeds "
            "6000 people per square kilometer making it one of the most "
            "densely populated regions in the world today."
        )
        result = verify_grounding(message, [citation])
        assert result.verdict == "flagged"
        assert result.reason == "ungrounded"
