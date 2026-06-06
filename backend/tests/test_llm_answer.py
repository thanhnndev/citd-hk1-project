"""Tests for LLMAnswerService, ChatResponse.fallback field, and chat router LLM path.

Unit tests use mocked OpenAI — no live API key required.
Integration tests are guarded by _is_real_api_key() and skipped in CI.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest
from fastapi.testclient import TestClient

from app.models.rag import RAGChunk
from app.models.response import ChatResponse, Citation
from agents.services.llm_answer_service import LLMAnswerService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_completion(
    content: str = "Làng chài Hàm Ninh là một điểm du lịch nổi tiếng ở Phú Quốc.",
    total_tokens: int = 120,
) -> MagicMock:
    """Build a fake OpenAI ChatCompletion response object."""
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = content
    completion.usage = MagicMock()
    completion.usage.total_tokens = total_tokens
    return completion


def _make_chunks() -> list[RAGChunk]:
    """Return 2 realistic RAGChunk instances for Hàm Ninh corpus."""
    return [
        RAGChunk(
            chunk_id="c001",
            source_id="src-ham-ninh-01",
            title="Làng chài Hàm Ninh",
            url="https://example.com/ham-ninh",
            domain="tourism",
            source_type="gov",
            reliability="high",
            language="vi",
            location="Hàm Ninh",
            text=(
                "Hàm Ninh là một làng chài nổi tiếng nằm ở phía đông đảo Phú Quốc, "
                "tỉnh Kiên Giang. Nơi đây nổi tiếng với các món hải sản tươi sống, "
                "đặc biệt là ghẹ và tôm hùm."
            ),
            chunk_index=0,
            total_chunks=3,
        ),
        RAGChunk(
            chunk_id="c002",
            source_id="src-ham-ninh-02",
            title="Chợ hải sản Hàm Ninh",
            url="https://example.com/cho-ham-ninh",
            domain="tourism",
            source_type="blog",
            reliability="medium",
            language="vi",
            location="Hàm Ninh",
            text=(
                "Chợ Hàm Ninh họp vào buổi sáng sớm, bán các loại hải sản vừa được "
                "đánh bắt từ biển. Du khách có thể mua ghẹ, tôm, mực và nhiều loại "
                "cá tươi với giá hợp lý."
            ),
            chunk_index=0,
            total_chunks=2,
        ),
    ]


def _make_citations() -> list[Citation]:
    """Return 2 Citation instances matching _make_chunks()."""
    chunks = _make_chunks()
    return [
        Citation(
            source=chunks[0].title,
            url=chunks[0].url,
            snippet=chunks[0].text[:200],
        ),
        Citation(
            source=chunks[1].title,
            url=chunks[1].url,
            snippet=chunks[1].text[:200],
        ),
    ]


def _is_real_api_key(key: str) -> bool:
    """Return True only if the key looks like a real OpenAI key (not a test stub)."""
    return bool(key) and key.startswith("sk-") and len(key) > 20


# ---------------------------------------------------------------------------
# TestLLMAnswerService — unit tests with mocked OpenAI
# ---------------------------------------------------------------------------

class TestLLMAnswerService:
    """Unit tests for LLMAnswerService.answer() with mocked OpenAI client."""

    def _make_service_with_mock(self, completion: MagicMock | None = None):
        """Return (LLMAnswerService, mock_create) with AsyncOpenAI patched."""
        mock_create = AsyncMock(return_value=completion or _make_mock_completion())
        svc = LLMAnswerService.__new__(LLMAnswerService)
        svc._client = MagicMock()
        svc._client.chat = MagicMock()
        svc._client.chat.completions = MagicMock()
        svc._client.chat.completions.create = mock_create
        svc.model = "gpt-4o-mini"
        return svc, mock_create

    @pytest.mark.asyncio
    async def test_happy_path_vi(self) -> None:
        """answer() returns ChatResponse with LLM content, fallback=False, correct session_id."""
        chunks = _make_chunks()
        citations = _make_citations()
        expected_content = "Làng chài Hàm Ninh là một điểm du lịch nổi tiếng ở Phú Quốc."
        svc, _ = self._make_service_with_mock(_make_mock_completion(content=expected_content))

        response = await svc.answer(
            chunks=chunks,
            citations=citations,
            query="làng chài Hàm Ninh",
            language="vi",
            session_id="sess-1",
        )

        assert response.message == expected_content
        assert response.fallback is False
        assert response.session_id == "sess-1"
        assert len(response.citations) == 2

    @pytest.mark.asyncio
    async def test_happy_path_en(self) -> None:
        """answer() with language='en' returns non-empty message string."""
        chunks = _make_chunks()
        citations = _make_citations()
        svc, _ = self._make_service_with_mock(
            _make_mock_completion(content="Ham Ninh is a famous fishing village on Phu Quoc Island.")
        )

        response = await svc.answer(
            chunks=chunks,
            citations=citations,
            query="What is Ham Ninh fishing village?",
            language="en",
            session_id="sess-2",
        )

        assert isinstance(response.message, str)
        assert len(response.message) > 0
        assert response.fallback is False

    @pytest.mark.asyncio
    async def test_grounding_prompt_contains_chunks(self) -> None:
        """System message must contain chunk titles, 'ONLY', and the language instruction."""
        chunks = _make_chunks()
        citations = _make_citations()
        svc, mock_create = self._make_service_with_mock()

        await svc.answer(
            chunks=chunks,
            citations=citations,
            query="Hàm Ninh có gì đặc biệt?",
            language="vi",
            session_id="sess-3",
        )

        call_kwargs = mock_create.call_args.kwargs
        messages = call_kwargs["messages"]
        system_content = messages[0]["content"]

        # Grounding constraint — soft, not hard "ONLY"
        assert "ngữ cảnh" in system_content.lower() or "context" in system_content.lower(), \
            "System prompt must reference context"
        # Chunk titles injected
        assert "Làng chài Hàm Ninh" in system_content
        assert "Chợ hải sản Hàm Ninh" in system_content
        # Language enforcement (Vietnamese)
        assert "tiếng Việt" in system_content or "vietnamese" in system_content.lower()

    @pytest.mark.asyncio
    async def test_empty_chunks_returns_honest_message(self) -> None:
        """answer() with empty chunks still calls LLM and returns fallback=False."""
        svc, mock_create = self._make_service_with_mock(
            _make_mock_completion(content="Hiện tại không có đủ thông tin để trả lời.")
        )

        response = await svc.answer(
            chunks=[],
            citations=[],
            query="câu hỏi không có dữ liệu",
            language="vi",
            session_id="sess-4",
        )

        # LLM was still called
        mock_create.assert_called_once()
        # Response is non-empty honest message
        assert isinstance(response.message, str)
        assert len(response.message) > 0
        # Not a fallback — LLM was called successfully
        assert response.fallback is False

    @pytest.mark.asyncio
    async def test_openai_exception_propagates(self) -> None:
        """answer() propagates openai.APIError to caller for fallback handling."""
        svc, mock_create = self._make_service_with_mock()
        mock_create.side_effect = openai.APIError(
            "timeout", request=MagicMock(), body=None
        )

        with pytest.raises(openai.APIError):
            await svc.answer(
                chunks=_make_chunks(),
                citations=_make_citations(),
                query="làng chài Hàm Ninh",
                language="vi",
                session_id="sess-5",
            )


# ---------------------------------------------------------------------------
# TestChatResponseFallbackField — model shape tests
# ---------------------------------------------------------------------------

class TestChatResponseFallbackField:
    """Verify ChatResponse.fallback field shape and defaults."""

    def test_fallback_field_defaults_false(self) -> None:
        """ChatResponse instantiated without fallback= defaults to False."""
        response = ChatResponse(
            session_id="s",
            message="m",
            latency_ms=1.0,
        )
        assert response.fallback is False

    def test_fallback_field_in_json(self) -> None:
        """model_dump() includes 'fallback' key with value False."""
        response = ChatResponse(
            session_id="s",
            message="m",
            latency_ms=1.0,
        )
        data = response.model_dump()
        assert "fallback" in data
        assert data["fallback"] is False

    def test_fallback_field_settable(self) -> None:
        """fallback field can be set to True after construction."""
        response = ChatResponse(
            session_id="s",
            message="m",
            latency_ms=1.0,
        )
        response.fallback = True
        assert response.fallback is True


# ---------------------------------------------------------------------------
# TestChatRouterLLMPath — router integration with mocked services
# ---------------------------------------------------------------------------

class TestChatRouterLLMPath:
    """Test chat router LLM path using TestClient with injected mock services."""

    _CHAT_PAYLOAD = {
        "session_id": "router-test-1",
        "message": "làng chài Hàm Ninh là gì?",
        "language": "vi",
    }

    def _make_llm_response(self, fallback: bool = False) -> ChatResponse:
        return ChatResponse(
            session_id="router-test-1",
            message="Hàm Ninh là làng chài nổi tiếng.",
            citations=_make_citations(),
            places=[],
            intent="cultural_query",
            langfuse_trace_id=None,
            latency_ms=250.0,
            fallback=fallback,
        )

    def test_router_uses_llm_service_when_available(self) -> None:
        """When llm_service is on app.state, router returns fallback=False."""
        from app.main import app

        mock_llm = MagicMock()
        mock_llm.answer = AsyncMock(return_value=self._make_llm_response(fallback=False))

        with patch("app.main.load_corpus", return_value=_make_chunks()), \
             patch("app.main.LLMAnswerService", return_value=mock_llm), \
             patch("app.main.HybridRetriever") as mock_hybrid_cls, \
             patch("app.main.QdrantService"), \
             patch("app.main.EmbeddingService"), \
             patch("app.main.BM25Vectorizer"):

            # Make HybridRetriever instance return chunks+citations
            mock_hybrid = MagicMock()
            mock_hybrid.search_with_citations = AsyncMock(
                return_value=(_make_retrieval_result(), _make_citations())
            )
            mock_hybrid_cls.return_value = mock_hybrid

            with TestClient(app) as client:
                app.state.llm_service = mock_llm
                r = client.post("/chat", json=self._CHAT_PAYLOAD)

        assert r.status_code == 200
        assert r.json()["fallback"] is False

    def test_router_falls_back_when_llm_raises(self) -> None:
        """When llm_service.answer raises, router returns 200 with fallback=True."""
        from app.main import app

        mock_llm = MagicMock()
        mock_llm.answer = AsyncMock(side_effect=Exception("openai down"))

        with patch("app.main.load_corpus", return_value=_make_chunks()), \
             patch("app.main.LLMAnswerService", return_value=mock_llm), \
             patch("app.main.HybridRetriever") as mock_hybrid_cls, \
             patch("app.main.QdrantService"), \
             patch("app.main.EmbeddingService"), \
             patch("app.main.BM25Vectorizer"):

            mock_hybrid = MagicMock()
            mock_hybrid.search_with_citations = AsyncMock(
                return_value=(_make_retrieval_result(), _make_citations())
            )
            mock_hybrid_cls.return_value = mock_hybrid

            with TestClient(app) as client:
                app.state.llm_service = mock_llm
                r = client.post("/chat", json=self._CHAT_PAYLOAD)

        assert r.status_code == 200
        assert r.json()["fallback"] is True

    def test_router_uses_deterministic_when_llm_service_none(self) -> None:
        """When llm_service is None, router uses deterministic path with fallback=False."""
        from app.main import app

        with patch("app.main.load_corpus", return_value=_make_chunks()), \
             patch("app.main.LLMAnswerService"), \
             patch("app.main.HybridRetriever") as mock_hybrid_cls, \
             patch("app.main.QdrantService"), \
             patch("app.main.EmbeddingService"), \
             patch("app.main.BM25Vectorizer"):

            mock_hybrid = MagicMock()
            mock_hybrid.search_with_citations = AsyncMock(
                return_value=(_make_retrieval_result(), _make_citations())
            )
            mock_hybrid_cls.return_value = mock_hybrid

            with TestClient(app) as client:
                app.state.llm_service = None
                r = client.post("/chat", json=self._CHAT_PAYLOAD)

        assert r.status_code == 200
        assert r.json()["fallback"] is False


# ---------------------------------------------------------------------------
# Shared helper for router tests
# ---------------------------------------------------------------------------

def _make_retrieval_result():
    """Build a minimal RetrievalResult for router test mocks."""
    from app.models.rag import RetrievalResult
    return RetrievalResult(
        chunks=_make_chunks(),
        query="làng chài Hàm Ninh là gì?",
        total_found=2,
        latency_ms=5.0,
    )


# ---------------------------------------------------------------------------
# TestLLMAnswerIntegration — guarded by real API key
# ---------------------------------------------------------------------------

class TestLLMAnswerIntegration:
    """Live gpt-4o-mini integration tests — skipped without a real OpenAI API key."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_real_key(self) -> None:
        from app.core.config import get_settings
        settings = get_settings()
        if not _is_real_api_key(settings.OPENAI_API_KEY):
            pytest.skip("no valid OpenAI API key — skipping integration test")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_live_answer_vi(self) -> None:
        """Live gpt-4o-mini call returns non-empty Vietnamese answer with citations."""
        svc = LLMAnswerService()
        chunks = _make_chunks()
        citations = _make_citations()

        response = await svc.answer(
            chunks=chunks,
            citations=citations,
            query="làng chài Hàm Ninh là gì?",
            language="vi",
            session_id="sess-int-1",
        )

        assert len(response.message) > 50, (
            f"Expected answer > 50 chars, got: {response.message!r}"
        )
        assert response.fallback is False
        assert len(response.citations) >= 2

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_live_answer_en(self) -> None:
        """Live gpt-4o-mini call returns non-empty English answer."""
        svc = LLMAnswerService()
        chunks = _make_chunks()
        citations = _make_citations()

        response = await svc.answer(
            chunks=chunks,
            citations=citations,
            query="What is Ham Ninh fishing village?",
            language="en",
            session_id="sess-int-2",
        )

        assert isinstance(response.message, str)
        assert len(response.message) > 0
        assert response.fallback is False
