"""Unit tests for GET /chat/stream SSE behavior."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure required env vars before importing app modules.
for _key in ("OPENAI_API_KEY", "GOONG_API_KEY", "GOONG_API_KEY"):
    os.environ.setdefault(_key, "fake-test-key")

from app.main import app
from app.models.rag import RAGChunk, RetrievalResult
from app.models.response import Citation


def _collect_sse_lines(response) -> list[str]:
    """Return data payloads from a buffered TestClient SSE response."""
    return [
        line.removeprefix("data: ")
        for line in response.text.split("\n")
        if line.startswith("data: ")
    ]


def _make_mock_stream(tokens: list[str]) -> AsyncIterator[MagicMock]:
    """Build an async iterable of OpenAI-like stream chunks."""
    async def _stream() -> AsyncIterator[MagicMock]:
        for token in [*tokens, None]:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = SimpleNamespace(content=token)
            yield chunk

    return _stream()


async def _tokens_from_mock_stream(tokens: list[str]) -> AsyncIterator[str]:
    """Adapt mock OpenAI chunks into the router's token stream contract."""
    async for chunk in _make_mock_stream(tokens):
        content = chunk.choices[0].delta.content
        if content:
            yield content


def _make_chunks() -> list[RAGChunk]:
    return [
        RAGChunk(
            chunk_id="c001",
            source_id="src-ham-ninh-01",
            title="Lang chai Ham Ninh",
            url="https://example.com/ham-ninh",
            domain="tourism",
            source_type="gov",
            reliability="high",
            language="vi",
            location="Ham Ninh",
            text="Ham Ninh la lang chai noi tieng voi hai san tuoi song.",
            chunk_index=0,
            total_chunks=1,
        )
    ]


def _make_citations() -> list[Citation]:
    chunk = _make_chunks()[0]
    return [Citation(source=chunk.title, url=chunk.url, snippet=chunk.text)]


def _make_retrieval_result(chunks: list[RAGChunk] | None = None) -> RetrievalResult:
    chunks = _make_chunks() if chunks is None else chunks
    return RetrievalResult(
        chunks=chunks,
        query="lang chai Ham Ninh",
        total_found=len(chunks),
        latency_ms=3.0,
    )


class _KeywordRetriever:
    def __init__(self, chunks: list[RAGChunk] | None = None) -> None:
        self._chunks = _make_chunks() if chunks is None else chunks

    def search_with_citations(self, query: str, top_k: int = 5):
        return _make_retrieval_result(self._chunks), _make_citations() if self._chunks else []


@pytest.fixture()
def sse_client():
    """TestClient with app startup dependencies patched away."""
    mock_llm = MagicMock()
    mock_llm.answer_stream = MagicMock(
        return_value=_tokens_from_mock_stream(["Xin", " chao"])
    )

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
            app.state.retriever = _KeywordRetriever()
            app.state.hybrid_retriever = mock_hybrid
            app.state.llm_service = mock_llm
            yield client, mock_llm, mock_hybrid


def _get_stream(client: TestClient, message: str = "lang chai Ham Ninh", session_id: str = "s1"):
    return client.get(
        "/chat/stream",
        params={"message": message, "session_id": session_id, "language": "vi"},
    )


class TestSSEEndpointFormat:
    def test_stream_returns_event_stream_content_type(self, sse_client) -> None:
        client, _, _ = sse_client

        response = _get_stream(client)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

    def test_stream_emits_done_sentinel(self, sse_client) -> None:
        client, _, _ = sse_client

        lines = _collect_sse_lines(_get_stream(client))

        assert "[DONE]" in lines

    def test_stream_emits_citations_event(self, sse_client) -> None:
        client, _, _ = sse_client

        lines = _collect_sse_lines(_get_stream(client))
        citations_events = [line for line in lines if line.startswith("[CITATIONS]")]

        assert len(citations_events) == 1
        citations = json.loads(citations_events[0].removeprefix("[CITATIONS] "))
        assert isinstance(citations, list)
        assert citations[0]["source"] == "Lang chai Ham Ninh"



    def test_stream_preserves_multiline_payload(self, sse_client) -> None:
        client, _, _ = sse_client

        lines = _collect_sse_lines(_get_stream(client, message="bạn giúp được gì nữa không?", session_id="s-multiline"))
        joined_text = "\n".join(line for line in lines if not line.startswith("["))

        assert "Mình có thể giúp theo 4 nhóm chính:" in joined_text
        assert "1. Tìm địa điểm" in joined_text
        assert "4. Giải thích gợi ý" in joined_text
        assert not any(line.startswith("[CITATIONS]") for line in lines)

class TestSSEFallbackPath:
    def test_stream_fallback_when_llm_service_none(self, sse_client) -> None:
        client, _, _ = sse_client
        app.state.llm_service = None
        app.state.agent_service._llm_service = None

        lines = _collect_sse_lines(_get_stream(client))

        assert any(line and not line.startswith("[") for line in lines)
        assert "[DONE]" in lines

    def test_stream_error_when_agent_stream_raises(self, sse_client) -> None:
        client, _, _ = sse_client
        agent = MagicMock()
        agent.checkpoint_mode = "test"

        async def _raise_stream(**kwargs):
            raise RuntimeError("agent down")
            yield "unreachable"

        agent.answer_stream = MagicMock(side_effect=_raise_stream)
        app.state.agent_service = agent

        lines = _collect_sse_lines(_get_stream(client))

        assert "[ERROR] RuntimeError" in lines
        assert "[DONE]" in lines


class TestSSEEdgeCases:
    def test_stream_empty_message_returns_error(self, sse_client) -> None:
        client, _, _ = sse_client

        lines = _collect_sse_lines(_get_stream(client, message="", session_id="s1"))

        assert "[ERROR] invalid_request" in lines
        assert "[DONE]" in lines

    def test_stream_no_retriever_returns_error(self, sse_client) -> None:
        client, _, _ = sse_client
        app.state.retriever = None
        app.state.hybrid_retriever = None

        lines = _collect_sse_lines(_get_stream(client))

        assert "[ERROR] service_unavailable" in lines
        assert "[DONE]" in lines

    def test_stream_empty_chunks_emits_honest_message(self, sse_client) -> None:
        client, mock_llm, mock_hybrid = sse_client
        mock_llm.answer_stream = MagicMock(
            return_value=_tokens_from_mock_stream(["Khong co du lieu."])
        )
        mock_hybrid.search_with_citations = AsyncMock(
            return_value=(_make_retrieval_result([]), [])
        )

        lines = _collect_sse_lines(_get_stream(client))

        called_kwargs = mock_llm.answer_stream.call_args.kwargs
        assert called_kwargs["chunks"] == []
        assert "Khong co du lieu." in lines
        assert "[DONE]" in lines

class TestSSEAgentDelegation:
    def test_stream_calls_agent_service_answer_stream(self, sse_client) -> None:
        client, _, _ = sse_client
        agent = MagicMock()
        agent.checkpoint_mode = "test"

        async def _answer_stream(**kwargs):
            yield "agent token"
            yield "[CITATIONS] []"
            yield "[DONE]"

        agent.answer_stream = MagicMock(side_effect=_answer_stream)
        app.state.agent_service = agent

        lines = _collect_sse_lines(_get_stream(client, message="agent question", session_id="agent-s1"))

        assert "agent token" in lines
        agent.answer_stream.assert_called_once_with(
            session_id="agent-s1",
            message="agent question",
            language="vi",
        )
