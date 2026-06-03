"""Tests for GroundedAnswerService — deterministic answer composition."""

from __future__ import annotations

import pytest

from app.models.rag import RAGChunk
from app.models.response import ChatResponse
from agents.guardrails.grounded_answer import (
    GroundedAnswerService,
    detect_intent,
    compose_answer_vi,
    compose_answer_en,
    _excerpt,
    _no_evidence_message,
)
from agents.tools.retriever import Retriever


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_chunk(
    chunk_id: str = "c1",
    title: str = "Test Source",
    text: str = "Hàm Ninh là một làng chài cổ ở Phú Quốc.",
    url: str | None = None,
) -> RAGChunk:
    return RAGChunk(
        chunk_id=chunk_id,
        source_id="s1",
        title=title,
        url=url or "https://example.com/source",
        domain="tourism",
        source_type="gov",
        reliability="high",
        language="vi",
        location="Hàm Ninh",
        text=text,
        chunk_index=0,
        total_chunks=1,
    )


@pytest.fixture
def empty_retriever():
    """Retriever over an empty corpus."""
    return Retriever([])


@pytest.fixture
def sample_chunks():
    """Small corpus for answer composition tests."""
    return [
        _make_chunk(
            chunk_id="c1",
            title="Làng Chài Hàm Ninh",
            text="Làng chài Hàm Ninh nằm ở phía đông đảo Phú Quốc, "
                 "là một trong những làng chài lâu đời nhất tại đây. "
                 "Người dân sống chủ yếu bằng nghề đánh bắt hải sản. "
                 "Chợ Hàm Ninh nổi tiếng với hải sản tươi sống như ghẹ, "
                 "cua, và tôm tích.",
            url="https://example.com/ham-ninh",
        ),
        _make_chunk(
            chunk_id="c2",
            title="Ẩm Thực Phú Quốc",
            text="Hải sản Phú Quốc nổi tiếng với sự tươi ngon và giá cả "
                 "phải chăng. Các món đặc sản gồm ghẹ Hàm Ninh, bún quậy, "
                 "và nước mắm Phú Quốc. Nhà hàng ven biển phục vụ hải sản "
                 "tươi sống chế biến tại chỗ.",
            url="https://example.com/food",
        ),
        _make_chunk(
            chunk_id="c3",
            title="Lịch Sử Hàm Ninh",
            text="Hàm Ninh có lịch sử hơn 200 năm, từng là trung tâm "
                 "thương mại của đảo Phú Quốc. Chợ Hàm Ninh được hình "
                 "thành từ thế kỷ 19, là nơi giao thương của thương nhân "
                 "Việt, Hoa và Khmer.",
            url="https://example.com/history",
        ),
    ]


@pytest.fixture
def populated_retriever(sample_chunks):
    """Retriever over the sample corpus."""
    return Retriever(sample_chunks)


@pytest.fixture
def service(populated_retriever):
    return GroundedAnswerService(populated_retriever)


# ---------------------------------------------------------------------------
# Intent detection tests
# ---------------------------------------------------------------------------

class TestDetectIntent:
    def test_restaurant_search_vi(self):
        assert detect_intent("nhà hàng hải sản ngon ở Hàm Ninh") == "restaurant_search"

    def test_restaurant_search_en(self):
        assert detect_intent("best seafood restaurant near me") == "restaurant_search"

    def test_restaurant_keyword_an(self):
        assert detect_intent("ăn gì ở Phú Quốc") == "restaurant_search"

    def test_restaurant_keyword_quan(self):
        assert detect_intent("quán ngon gần đây") == "restaurant_search"

    def test_navigation_vi(self):
        assert detect_intent("đường đi đến làng chài Hàm Ninh") == "navigation"

    def test_navigation_en(self):
        assert detect_intent("how to get to Ham Ninh fishing village") == "navigation"

    def test_navigation_chỉ_đường(self):
        assert detect_intent("chỉ đường đến chợ Hàm Ninh") == "navigation"

    def test_cultural_query_default(self):
        assert detect_intent("Hàm Ninh có gì thú vị?") == "cultural_query"

    def test_cultural_query_history(self):
        assert detect_intent("lịch sử hình thành làng chài Hàm Ninh") == "cultural_query"

    def test_unknown_short(self):
        assert detect_intent("a") == "unknown"

    def test_unknown_very_short(self):
        assert detect_intent("") == "unknown"

    def test_unknown_two_chars(self):
        assert detect_intent("ab") == "unknown"


# ---------------------------------------------------------------------------
# Excerpt helper tests
# ---------------------------------------------------------------------------

class TestExcerpt:
    def test_short_text_unchanged(self):
        assert _excerpt("Hello world") == "Hello world"

    def test_long_text_truncated(self):
        long = "A" * 200
        result = _excerpt(long)
        assert len(result) <= 153  # 150 + "..."
        assert result.endswith("...")

    def test_truncate_at_word_boundary(self):
        # Text longer than 150 chars to force truncation
        text = " ".join(["word"] * 50)  # ~250 chars
        result = _excerpt(text)
        assert result.endswith("...")
        # The part before "..." should not end mid-word
        body = result[:-3]
        assert body and (body[-1].isalnum() or body[-1] in ".,;:!?")


# ---------------------------------------------------------------------------
# No-evidence message tests
# ---------------------------------------------------------------------------

class TestNoEvidenceMessage:
    def test_vi_message(self):
        msg = _no_evidence_message("vi")
        assert "chưa có thông tin" in msg
        # Must NOT contain any factual claim about Hàm Ninh
        assert "Hàm Ninh" not in msg
        assert "hải sản" not in msg

    def test_en_message(self):
        msg = _no_evidence_message("en")
        assert "do not have sufficient information" in msg
        # Must NOT contain any factual claim
        assert "Hàm Ninh" not in msg
        assert "seafood" not in msg

    def test_unknown_language_defaults_to_en(self):
        msg = _no_evidence_message("fr")
        assert msg == _no_evidence_message("en")

    def test_no_evidence_vi_uppercase_lang(self):
        msg = _no_evidence_message("VI")
        assert "chưa có thông tin" in msg


# ---------------------------------------------------------------------------
# Answer composition tests (Vietnamese)
# ---------------------------------------------------------------------------

class TestComposeAnswerVi:
    def test_single_chunk(self):
        chunks = [_make_chunk(title="Source A", text="Content about A.")]
        result = compose_answer_vi("test", chunks)
        assert result.startswith("Về Hàm Ninh, các nguồn hiện có cho thấy:")
        assert "Content about A" in result

    def test_multiple_chunks(self):
        chunks = [
            _make_chunk(chunk_id="c1", title="Source A", text="Content A."),
            _make_chunk(chunk_id="c2", title="Source B", text="Content B."),
        ]
        result = compose_answer_vi("test", chunks)
        assert result.startswith("Về Hàm Ninh, các nguồn hiện có cho thấy:")
        assert "Content A" in result
        assert "Content B" in result

    def test_empty_results(self):
        result = compose_answer_vi("test", [])
        assert "chưa có thông tin" in result


# ---------------------------------------------------------------------------
# Answer composition tests (English)
# ---------------------------------------------------------------------------

class TestComposeAnswerEn:
    def test_single_chunk(self):
        chunks = [_make_chunk(title="Nguồn Việt", text="Nội dung tiếng Việt.")]
        result = compose_answer_en("test", chunks)
        assert "About Ham Ninh" in result
        assert "Nội dung tiếng Việt" in result

    def test_multiple_chunks(self):
        chunks = [
            _make_chunk(chunk_id="c1", title="Nguồn A", text="Nội dung A."),
            _make_chunk(chunk_id="c2", title="Nguồn B", text="Nội dung B."),
        ]
        result = compose_answer_en("test", chunks)
        assert result.startswith("About Ham Ninh")
        assert "Nội dung A" in result
        assert "Nội dung B" in result

    def test_empty_results(self):
        result = compose_answer_en("test", [])
        assert "do not have sufficient information" in result


# ---------------------------------------------------------------------------
# GroundedAnswerService.answer() integration tests
# ---------------------------------------------------------------------------

class TestGroundedAnswerServiceAnswer:
    def test_success_returns_valid_response(self, service):
        resp = service.answer("Hàm Ninh hải sản", "vi", "sess-001")
        assert isinstance(resp, ChatResponse)
        assert resp.session_id == "sess-001"
        assert resp.message
        assert resp.intent is not None
        assert resp.latency_ms >= 0
        assert resp.langfuse_trace_id is None
        assert resp.places == []

    def test_success_has_citations(self, service):
        resp = service.answer("làng chài Hàm Ninh", "vi", "sess-002")
        # If retrieval found results, citations should be present
        if resp.message and "chưa có thông tin" not in resp.message:
            assert len(resp.citations) > 0
            assert resp.citations[0].source is not None

    def test_no_evidence_empty_corpus(self, empty_retriever):
        svc = GroundedAnswerService(empty_retriever)
        resp = svc.answer("anything at all", "vi", "sess-003")
        assert "chưa có thông tin" in resp.message
        assert resp.citations == []
        assert resp.intent is not None
        assert resp.latency_ms >= 0

    def test_no_evidence_en_language(self, empty_retriever):
        svc = GroundedAnswerService(empty_retriever)
        resp = svc.answer("unknown topic", "en", "sess-004")
        assert "do not have sufficient information" in resp.message
        assert resp.citations == []

    def test_english_response(self, service):
        resp = service.answer("Hàm Ninh history", "en", "sess-005")
        assert isinstance(resp, ChatResponse)
        assert resp.session_id == "sess-005"
        assert resp.latency_ms >= 0

    def test_intent_detected_on_miss(self, empty_retriever):
        svc = GroundedAnswerService(empty_retriever)
        resp = svc.answer("nhà hàng ngon", "vi", "sess-006")
        # Even with no evidence, intent should be classified
        assert resp.intent == "restaurant_search"

    def test_latency_always_present(self, service):
        resp = service.answer("test query", "vi", "sess-007")
        assert isinstance(resp.latency_ms, float)
        assert resp.latency_ms >= 0
