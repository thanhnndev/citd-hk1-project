"""Unit tests for rag_agent_node and grade_documents_node.

Covers the full RAG pipeline with mocked services:
- rag_agent_node: retrieval → Cohere reranking → LLM answer generation
- grade_documents_node: LLM structured-output relevance grading

Tests cover success paths, Cohere failure, LLM failure, no-chunks,
no-LLM passthrough, and mixed-grade scenarios.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.graph.nodes import (
    NodeServices,
    configure_services,
    get_services,
    rag_agent_node,
    grade_documents_node,
    rewrite_query_node,
)
from app.models.rag import RAGChunk, RetrievalResult
from app.models.response import ChatResponse, Citation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunk(
    index: int = 0,
    title: str = "Làng chài Hàm Ninh",
    text: str = "Hàm Ninh là làng chài cổ nằm ở phía đông đảo Phú Quốc.",
    url: str | None = "https://example.com/ham-ninh",
) -> RAGChunk:
    """Create a minimal RAGChunk for testing."""
    return RAGChunk(
        chunk_id=f"chunk-{index}",
        source_id=f"src-{index}",
        title=title,
        url=url,
        domain="tourism",
        source_type="blog",
        reliability="high",
        language="vi",
        location="Hàm Ninh",
        text=text,
        chunk_index=index,
        total_chunks=1,
    )


def _make_chunks(n: int) -> list[RAGChunk]:
    """Create n distinct RAGChunks."""
    return [
        _make_chunk(
            index=i,
            title=f"Chunk Title {i}",
            text=f"Chunk text content for chunk number {i}. "
            f"This is about Hàm Ninh tourism and culture.",
        )
        for i in range(n)
    ]


def _make_retrieval_result(chunks: list[RAGChunk]) -> RetrievalResult:
    """Wrap chunks in a RetrievalResult."""
    return RetrievalResult(
        chunks=chunks,
        query="test query",
        total_found=len(chunks),
        latency_ms=5.0,
    )


def _make_mock_completion(binary_score: str = "yes") -> MagicMock:
    """Create a mock OpenAI completion with a JSON response."""
    content = json.dumps({"binary_score": binary_score})
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]
    return mock_completion


def _make_chat_response(message: str = "Đây là câu trả lời từ LLM.") -> ChatResponse:
    """Create a ChatResponse for mocking LLMAnswerService."""
    return ChatResponse(
        session_id="test-session",
        message=message,
        citations=[],
        places=[],
        intent="cultural_query",
        latency_ms=100.0,
        fallback=False,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_services():
    """Reset NodeServices to defaults after each test."""
    yield
    configure_services(NodeServices())


@pytest.fixture
def mock_retriever():
    """A mock retriever with a sync search() method."""
    retriever = MagicMock()
    return retriever


@pytest.fixture
def mock_cohere_reranker():
    """A mock CohereReranker with an async rerank() method."""
    reranker = AsyncMock()
    return reranker


@pytest.fixture
def mock_llm_answer_service():
    """A mock LLMAnswerService with an async answer() method."""
    service = AsyncMock()
    return service


@pytest.fixture
def mock_llm_client():
    """A mock OpenAI AsyncOpenAI client."""
    client = MagicMock()
    client.chat.completions.create = AsyncMock()
    return client


# ===========================================================================
# Section 1: rag_agent_node tests
# ===========================================================================


class TestRagAgentNode:
    """Tests for rag_agent_node: retrieval → reranking → answer generation."""

    @pytest.mark.asyncio
    async def test_success_path_full_pipeline(
        self,
        mock_retriever,
        mock_cohere_reranker,
        mock_llm_answer_service,
    ):
        """Full pipeline: retrieve 10, rerank to 5, LLM generates answer."""
        chunks_10 = _make_chunks(10)
        chunks_5 = chunks_10[:5]

        # Retriever returns 10 chunks
        mock_retriever.search.return_value = _make_retrieval_result(chunks_10)

        # Cohere reranks to 5
        mock_cohere_reranker.rerank.return_value = chunks_5

        # LLMAnswerService returns answer
        mock_llm_answer_service.answer.return_value = _make_chat_response(
            "Hàm Ninh là làng chài nổi tiếng với hải sản tươi sống."
        )

        services = NodeServices(
            retriever=mock_retriever,
            cohere_reranker=mock_cohere_reranker,
            llm_answer_service=mock_llm_answer_service,
        )
        configure_services(services)

        state = {
            "message": "Làng chài Hàm Ninh có gì đặc biệt?",
            "language": "vi",
            "session_id": "test-session-001",
        }

        result = await rag_agent_node(state)

        # Verify state updates
        assert len(result["knowledge_chunks"]) == 5
        assert len(result["citations"]) == 5
        assert result["response_text"] == "Hàm Ninh là làng chài nổi tiếng với hải sản tươi sống."
        assert result["knowledge_response_ready"] is True

        # Verify retriever called with top_k=10
        mock_retriever.search.assert_called_once_with(
            "Làng chài Hàm Ninh có gì đặc biệt?", top_k=10
        )

        # Verify Cohere called with top_n=5
        mock_cohere_reranker.rerank.assert_called_once()
        call_args = mock_cohere_reranker.rerank.call_args
        assert call_args[0][0] == "Làng chài Hàm Ninh có gì đặc biệt?"
        assert len(call_args[0][1]) == 10  # received all 10 chunks
        assert call_args[1]["top_n"] == 5

        # Verify LLMAnswerService called with reranked chunks
        mock_llm_answer_service.answer.assert_called_once()
        answer_kwargs = mock_llm_answer_service.answer.call_args[1]
        assert len(answer_kwargs["chunks"]) == 5
        assert len(answer_kwargs["citations"]) == 5
        assert answer_kwargs["query"] == "Làng chài Hàm Ninh có gì đặc biệt?"
        assert answer_kwargs["language"] == "vi"

    @pytest.mark.asyncio
    async def test_cohere_failure_fallback_to_chunks_slice(
        self,
        mock_retriever,
        mock_cohere_reranker,
        mock_llm_answer_service,
    ):
        """When Cohere raises, node falls back to chunks[:5]."""
        chunks_10 = _make_chunks(10)

        mock_retriever.search.return_value = _make_retrieval_result(chunks_10)

        # Cohere fails
        mock_cohere_reranker.rerank.side_effect = Exception("Cohere API rate limit")

        # LLM still works with fallback chunks
        mock_llm_answer_service.answer.return_value = _make_chat_response(
            "Thông tin từ检索 kết quả ban đầu."
        )

        services = NodeServices(
            retriever=mock_retriever,
            cohere_reranker=mock_cohere_reranker,
            llm_answer_service=mock_llm_answer_service,
        )
        configure_services(services)

        state = {
            "message": "Văn hóa làng chài",
            "language": "vi",
            "session_id": "test-session-002",
        }

        result = await rag_agent_node(state)

        # Should fall back to first 5 chunks from retriever
        assert len(result["knowledge_chunks"]) == 5
        assert len(result["citations"]) == 5
        assert result["knowledge_response_ready"] is True

        # Verify LLM was still called (with fallback chunks)
        mock_llm_answer_service.answer.assert_called_once()
        answer_kwargs = mock_llm_answer_service.answer.call_args[1]
        assert len(answer_kwargs["chunks"]) == 5

    @pytest.mark.asyncio
    async def test_llm_failure_deterministic_fallback(
        self,
        mock_retriever,
        mock_cohere_reranker,
        mock_llm_answer_service,
    ):
        """When LLMAnswerService raises, node produces deterministic text."""
        chunks_10 = _make_chunks(10)
        chunks_5 = chunks_10[:5]

        mock_retriever.search.return_value = _make_retrieval_result(chunks_10)
        mock_cohere_reranker.rerank.return_value = chunks_5

        # LLM fails
        mock_llm_answer_service.answer.side_effect = Exception("OpenAI rate limit exceeded")

        services = NodeServices(
            retriever=mock_retriever,
            cohere_reranker=mock_cohere_reranker,
            llm_answer_service=mock_llm_answer_service,
        )
        configure_services(services)

        state = {
            "message": "Lịch sử Hàm Ninh",
            "language": "vi",
            "session_id": "test-session-003",
        }

        result = await rag_agent_node(state)

        # Should produce deterministic fallback text
        assert result["knowledge_response_ready"] is True
        assert len(result["knowledge_chunks"]) == 5
        assert len(result["citations"]) == 5
        # Fallback text should reference chunk content
        assert "Dựa trên thông tin" in result["response_text"]
        assert "Chunk Title 0" in result["response_text"]

    @pytest.mark.asyncio
    async def test_llm_failure_deterministic_fallback_english(
        self,
        mock_retriever,
        mock_cohere_reranker,
        mock_llm_answer_service,
    ):
        """LLM failure with language=en produces English fallback."""
        chunks_10 = _make_chunks(10)
        chunks_5 = chunks_10[:5]

        mock_retriever.search.return_value = _make_retrieval_result(chunks_10)
        mock_cohere_reranker.rerank.return_value = chunks_5
        mock_llm_answer_service.answer.side_effect = Exception("API timeout")

        services = NodeServices(
            retriever=mock_retriever,
            cohere_reranker=mock_cohere_reranker,
            llm_answer_service=mock_llm_answer_service,
        )
        configure_services(services)

        state = {
            "message": "History of Ham Ninh",
            "language": "en",
            "session_id": "test-session-004",
        }

        result = await rag_agent_node(state)

        assert "Based on available information" in result["response_text"]
        assert result["knowledge_response_ready"] is True

    @pytest.mark.asyncio
    async def test_no_retriever_no_chunks(
        self,
        mock_llm_answer_service,
    ):
        """When retriever is None, node produces 'no chunks' response."""
        services = NodeServices(
            retriever=None,
            cohere_reranker=None,
            llm_answer_service=mock_llm_answer_service,
        )
        configure_services(services)

        state = {
            "message": "Thông tin về Hàm Ninh",
            "language": "vi",
            "session_id": "test-session-005",
        }

        result = await rag_agent_node(state)

        assert result["knowledge_chunks"] == []
        assert result["citations"] == []
        assert result["knowledge_response_ready"] is True
        # No-chunks fallback message
        assert "chưa có thông tin" in result["response_text"]

    @pytest.mark.asyncio
    async def test_retriever_failure_empty_chunks(
        self,
        mock_retriever,
    ):
        """When retriever.search() raises, chunks list is empty."""
        mock_retriever.search.side_effect = Exception("Qdrant connection failed")

        services = NodeServices(
            retriever=mock_retriever,
            cohere_reranker=None,
            llm_answer_service=None,
        )
        configure_services(services)

        state = {
            "message": "Văn hóa Hàm Ninh",
            "language": "vi",
            "session_id": "test-session-006",
        }

        result = await rag_agent_node(state)

        assert result["knowledge_chunks"] == []
        assert result["citations"] == []
        assert result["knowledge_response_ready"] is True

    @pytest.mark.asyncio
    async def test_no_cohere_skips_reranking(
        self,
        mock_retriever,
        mock_llm_answer_service,
    ):
        """When cohere_reranker is None, chunks are used as-is (no rerank)."""
        chunks_10 = _make_chunks(10)
        mock_retriever.search.return_value = _make_retrieval_result(chunks_10)

        mock_llm_answer_service.answer.return_value = _make_chat_response("Answer text")

        services = NodeServices(
            retriever=mock_retriever,
            cohere_reranker=None,  # No reranker
            llm_answer_service=mock_llm_answer_service,
        )
        configure_services(services)

        state = {
            "message": "Hải sản Hàm Ninh",
            "language": "vi",
            "session_id": "test-session-007",
        }

        result = await rag_agent_node(state)

        # All 10 chunks should pass through (no Cohere truncation to 5)
        assert len(result["knowledge_chunks"]) == 10
        assert len(result["citations"]) == 10

    @pytest.mark.asyncio
    async def test_no_llm_service_deterministic_response(
        self,
        mock_retriever,
        mock_cohere_reranker,
    ):
        """When llm_answer_service is None, node produces deterministic text."""
        chunks_10 = _make_chunks(10)
        chunks_5 = chunks_10[:5]

        mock_retriever.search.return_value = _make_retrieval_result(chunks_10)
        mock_cohere_reranker.rerank.return_value = chunks_5

        services = NodeServices(
            retriever=mock_retriever,
            cohere_reranker=mock_cohere_reranker,
            llm_answer_service=None,  # No LLM
        )
        configure_services(services)

        state = {
            "message": "Văn hóa làng chài",
            "language": "vi",
            "session_id": "test-session-008",
        }

        result = await rag_agent_node(state)

        assert len(result["knowledge_chunks"]) == 5
        assert result["knowledge_response_ready"] is True
        # Deterministic fallback
        assert "Dựa trên thông tin" in result["response_text"]

    @pytest.mark.asyncio
    async def test_async_retriever_handled(
        self,
        mock_cohere_reranker,
        mock_llm_answer_service,
    ):
        """Node handles async retriever (inspect.isawaitable path)."""
        chunks_10 = _make_chunks(10)
        chunks_5 = chunks_10[:5]

        # Create an async retriever mock
        async_retriever = MagicMock()
        async_retriever.search = AsyncMock(
            return_value=_make_retrieval_result(chunks_10)
        )

        mock_cohere_reranker.rerank.return_value = chunks_5
        mock_llm_answer_service.answer.return_value = _make_chat_response("Async answer")

        services = NodeServices(
            retriever=async_retriever,
            cohere_reranker=mock_cohere_reranker,
            llm_answer_service=mock_llm_answer_service,
        )
        configure_services(services)

        state = {
            "message": "Test async retriever",
            "language": "vi",
            "session_id": "test-session-009",
        }

        result = await rag_agent_node(state)

        assert len(result["knowledge_chunks"]) == 5
        assert result["knowledge_response_ready"] is True
        assert result["response_text"] == "Async answer"

    @pytest.mark.asyncio
    async def test_citations_built_from_chunks(
        self,
        mock_retriever,
    ):
        """Citations are correctly built from knowledge chunks."""
        chunks = [
            _make_chunk(0, "Title A", "Text A content", "https://a.com"),
            _make_chunk(1, "Title B", "Text B content", "https://b.com"),
        ]
        mock_retriever.search.return_value = _make_retrieval_result(chunks)

        services = NodeServices(
            retriever=mock_retriever,
            cohere_reranker=None,
            llm_answer_service=None,
        )
        configure_services(services)

        state = {
            "message": "Test citations",
            "language": "vi",
            "session_id": "test-session-010",
        }

        result = await rag_agent_node(state)

        assert len(result["citations"]) == 2
        assert result["citations"][0].source == "Title A"
        assert result["citations"][0].url == "https://a.com"
        assert result["citations"][1].source == "Title B"
        assert result["citations"][1].url == "https://b.com"

    @pytest.mark.asyncio
    async def test_rag_agent_uses_rewritten_query(
        self,
        mock_retriever,
    ):
        """When state has rewritten_query, rag_agent uses it instead of message."""
        chunks = _make_chunks(3)
        mock_retriever.search.return_value = _make_retrieval_result(chunks)

        services = NodeServices(
            retriever=mock_retriever,
            cohere_reranker=None,
            llm_answer_service=None,
        )
        configure_services(services)

        state = {
            "message": "original vague query",
            "rewritten_query": "văn hóa làng chài Hàm Ninh Phú Quốc truyền thống",
            "language": "vi",
            "session_id": "test-rewrite-usage-001",
        }

        result = await rag_agent_node(state)

        # Retriever should be called with rewritten_query, NOT message
        mock_retriever.search.assert_called_once_with(
            "văn hóa làng chài Hàm Ninh Phú Quốc truyền thống", top_k=10
        )
        assert result["knowledge_response_ready"] is True

    @pytest.mark.asyncio
    async def test_rag_agent_falls_back_to_message(
        self,
        mock_retriever,
    ):
        """When state has no rewritten_query, rag_agent falls back to message."""
        chunks = _make_chunks(3)
        mock_retriever.search.return_value = _make_retrieval_result(chunks)

        services = NodeServices(
            retriever=mock_retriever,
            cohere_reranker=None,
            llm_answer_service=None,
        )
        configure_services(services)

        state = {
            "message": "Làng chài Hàm Ninh có gì đặc biệt?",
            "language": "vi",
            "session_id": "test-rewrite-usage-002",
        }

        result = await rag_agent_node(state)

        # Retriever should be called with message (no rewritten_query in state)
        mock_retriever.search.assert_called_once_with(
            "Làng chài Hàm Ninh có gì đặc biệt?", top_k=10
        )
        assert result["knowledge_response_ready"] is True


# ===========================================================================
# Section 2: grade_documents_node tests
# ===========================================================================


class TestGradeDocumentsNode:
    """Tests for grade_documents_node: LLM-based relevance grading."""

    @pytest.mark.asyncio
    async def test_all_relevant_chunks(
        self,
        mock_llm_client,
    ):
        """5 chunks all graded 'yes' → grade_score=1.0, grade_label='relevant'."""
        chunks = _make_chunks(5)

        # All chunks return 'yes'
        mock_llm_client.chat.completions.create.return_value = _make_mock_completion("yes")

        services = NodeServices(
            llm_client=mock_llm_client,
        )
        configure_services(services)

        state = {
            "knowledge_chunks": chunks,
            "message": "Văn hóa làng chài Hàm Ninh",
            "session_id": "test-grade-001",
        }

        result = await grade_documents_node(state)

        assert result["grade_score"] == 1.0
        assert result["grade_label"] == "relevant"
        # Should have called LLM 5 times (once per chunk)
        assert mock_llm_client.chat.completions.create.call_count == 5

    @pytest.mark.asyncio
    async def test_all_irrelevant_chunks(
        self,
        mock_llm_client,
    ):
        """5 chunks all graded 'no' → grade_score=0.0, grade_label='irrelevant'."""
        chunks = _make_chunks(5)

        mock_llm_client.chat.completions.create.return_value = _make_mock_completion("no")

        services = NodeServices(
            llm_client=mock_llm_client,
        )
        configure_services(services)

        state = {
            "knowledge_chunks": chunks,
            "message": "Nhà hàng ở đâu?",
            "session_id": "test-grade-002",
        }

        result = await grade_documents_node(state)

        assert result["grade_score"] == 0.0
        assert result["grade_label"] == "irrelevant"
        assert mock_llm_client.chat.completions.create.call_count == 5

    @pytest.mark.asyncio
    async def test_mixed_chunks(
        self,
        mock_llm_client,
    ):
        """3 yes + 2 no → grade_score=0.6, grade_label='relevant'."""
        chunks = _make_chunks(5)

        # Create alternating responses: yes, yes, yes, no, no
        responses = [
            _make_mock_completion("yes"),
            _make_mock_completion("yes"),
            _make_mock_completion("yes"),
            _make_mock_completion("no"),
            _make_mock_completion("no"),
        ]
        mock_llm_client.chat.completions.create.side_effect = responses

        services = NodeServices(
            llm_client=mock_llm_client,
        )
        configure_services(services)

        state = {
            "knowledge_chunks": chunks,
            "message": "Lịch sử và nhà hàng",
            "session_id": "test-grade-003",
        }

        result = await grade_documents_node(state)

        assert result["grade_score"] == pytest.approx(0.6)
        assert result["grade_label"] == "relevant"  # 0.6 >= 0.5

    @pytest.mark.asyncio
    async def test_no_chunks_irrelevant(self):
        """Empty knowledge_chunks → grade_score=0.0, grade_label='irrelevant'."""
        services = NodeServices(
            llm_client=MagicMock(),  # LLM client present but irrelevant
        )
        configure_services(services)

        state = {
            "knowledge_chunks": [],
            "message": "Thông tin gì đó",
            "session_id": "test-grade-004",
        }

        result = await grade_documents_node(state)

        assert result["grade_score"] == 0.0
        assert result["grade_label"] == "irrelevant"

    @pytest.mark.asyncio
    async def test_no_chunks_none_value(self):
        """None knowledge_chunks → grade_score=0.0, grade_label='irrelevant'."""
        services = NodeServices()
        configure_services(services)

        state = {
            "knowledge_chunks": None,
            "message": "Test",
            "session_id": "test-grade-005",
        }

        result = await grade_documents_node(state)

        assert result["grade_score"] == 0.0
        assert result["grade_label"] == "irrelevant"

    @pytest.mark.asyncio
    async def test_no_llm_passthrough(self):
        """llm_client=None → grade_score=1.0, grade_label='relevant' (pass-through)."""
        chunks = _make_chunks(5)

        services = NodeServices(
            llm_client=None,
        )
        configure_services(services)

        state = {
            "knowledge_chunks": chunks,
            "message": "Văn hóa Hàm Ninh",
            "session_id": "test-grade-006",
        }

        result = await grade_documents_node(state)

        assert result["grade_score"] == 1.0
        assert result["grade_label"] == "relevant"

    @pytest.mark.asyncio
    async def test_llm_failure_optimistic_fallback(
        self,
        mock_llm_client,
    ):
        """Per-chunk LLM failure → assume relevant (score 1.0 per chunk)."""
        chunks = _make_chunks(5)

        # All LLM calls fail
        mock_llm_client.chat.completions.create.side_effect = Exception(
            "OpenAI API connection timeout"
        )

        services = NodeServices(
            llm_client=mock_llm_client,
        )
        configure_services(services)

        state = {
            "knowledge_chunks": chunks,
            "message": "Văn hóa làng chài",
            "session_id": "test-grade-007",
        }

        result = await grade_documents_node(state)

        # All chunks assumed relevant on failure (optimistic)
        assert result["grade_score"] == 1.0
        assert result["grade_label"] == "relevant"
        assert mock_llm_client.chat.completions.create.call_count == 5

    @pytest.mark.asyncio
    async def test_partial_llm_failure(
        self,
        mock_llm_client,
    ):
        """Some chunks succeed, some fail → mixed score with failures as 1.0."""
        chunks = _make_chunks(5)

        # Chunk 0: yes (1.0), Chunk 1: fails (1.0), Chunk 2: no (0.0),
        # Chunk 3: yes (1.0), Chunk 4: fails (1.0)
        responses = [
            _make_mock_completion("yes"),
            Exception("Rate limit"),
            _make_mock_completion("no"),
            _make_mock_completion("yes"),
            Exception("Timeout"),
        ]
        mock_llm_client.chat.completions.create.side_effect = responses

        services = NodeServices(
            llm_client=mock_llm_client,
        )
        configure_services(services)

        state = {
            "knowledge_chunks": chunks,
            "message": "Mixed query",
            "session_id": "test-grade-008",
        }

        result = await grade_documents_node(state)

        # Scores: [1.0, 1.0, 0.0, 1.0, 1.0] → mean = 0.8
        assert result["grade_score"] == pytest.approx(0.8)
        assert result["grade_label"] == "relevant"

    @pytest.mark.asyncio
    async def test_limits_to_top_5_chunks(
        self,
        mock_llm_client,
    ):
        """Even with 10 chunks, only top-5 are graded (latency cap)."""
        chunks = _make_chunks(10)

        mock_llm_client.chat.completions.create.return_value = _make_mock_completion("yes")

        services = NodeServices(
            llm_client=mock_llm_client,
        )
        configure_services(services)

        state = {
            "knowledge_chunks": chunks,
            "message": "Test grading limit",
            "session_id": "test-grade-009",
        }

        result = await grade_documents_node(state)

        # Only 5 LLM calls despite 10 chunks
        assert mock_llm_client.chat.completions.create.call_count == 5
        assert result["grade_score"] == 1.0
        assert result["grade_label"] == "relevant"

    @pytest.mark.asyncio
    async def test_grade_label_boundary_at_0_5(
        self,
        mock_llm_client,
    ):
        """Exactly 0.5 score → grade_label='relevant' (>= threshold)."""
        chunks = _make_chunks(2)

        # 1 yes + 1 no → 0.5
        responses = [
            _make_mock_completion("yes"),
            _make_mock_completion("no"),
        ]
        mock_llm_client.chat.completions.create.side_effect = responses

        services = NodeServices(
            llm_client=mock_llm_client,
        )
        configure_services(services)

        state = {
            "knowledge_chunks": chunks,
            "message": "Boundary test",
            "session_id": "test-grade-010",
        }

        result = await grade_documents_node(state)

        assert result["grade_score"] == pytest.approx(0.5)
        assert result["grade_label"] == "relevant"  # >= 0.5

    @pytest.mark.asyncio
    async def test_below_threshold_irrelevant(
        self,
        mock_llm_client,
    ):
        """Score < 0.5 → grade_label='irrelevant'."""
        chunks = _make_chunks(4)

        # 1 yes + 3 no → 0.25
        responses = [
            _make_mock_completion("yes"),
            _make_mock_completion("no"),
            _make_mock_completion("no"),
            _make_mock_completion("no"),
        ]
        mock_llm_client.chat.completions.create.side_effect = responses

        services = NodeServices(
            llm_client=mock_llm_client,
        )
        configure_services(services)

        state = {
            "knowledge_chunks": chunks,
            "message": "Irrelevant test",
            "session_id": "test-grade-011",
        }

        result = await grade_documents_node(state)

        assert result["grade_score"] == pytest.approx(0.25)
        assert result["grade_label"] == "irrelevant"

    @pytest.mark.asyncio
    async def test_llm_called_with_correct_params(
        self,
        mock_llm_client,
    ):
        """Verify LLM is called with GradeDocuments response_format and correct structure."""
        chunks = [_make_chunk(0, "Test Title", "Test content for grading")]

        mock_llm_client.chat.completions.create.return_value = _make_mock_completion("yes")

        from agents.graph.state import GradeDocuments

        services = NodeServices(
            llm_client=mock_llm_client,
        )
        configure_services(services)

        state = {
            "knowledge_chunks": chunks,
            "message": "What is Ham Ninh culture?",
            "session_id": "test-grade-012",
        }

        result = await grade_documents_node(state)

        # Verify the LLM call structure
        call_kwargs = mock_llm_client.chat.completions.create.call_args[1]
        assert call_kwargs["response_format"] == GradeDocuments
        assert call_kwargs["max_completion_tokens"] == 32

        # Verify messages contain system prompt and user content
        messages = call_kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "relevance grader" in messages[0]["content"].lower()
        assert messages[1]["role"] == "user"
        assert "Test Title" in messages[1]["content"]
        assert "What is Ham Ninh culture?" in messages[1]["content"]


# ---------------------------------------------------------------------------
# RewriteQuery mock helper
# ---------------------------------------------------------------------------


def _make_rewrite_completion(
    rewritten_query: str = "văn hóa làng chài Hàm Ninh Phú Quốc truyền thống",
    reasoning: str = "Added location context for better retrieval",
) -> MagicMock:
    """Create a mock OpenAI completion with a RewriteQuery JSON response."""
    content = json.dumps({"rewritten_query": rewritten_query, "reasoning": reasoning})
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]
    return mock_completion


# ===========================================================================
# Section 3: rewrite_query_node tests
# ===========================================================================


class TestRewriteQueryNode:
    """Tests for rewrite_query_node: LLM structured-output query rewrite."""

    @pytest.mark.asyncio
    async def test_success_path_with_mocked_llm(
        self,
        mock_llm_client,
    ):
        """LLM returns valid RewriteQuery → rewritten_query is set, rewrite_count incremented."""
        mock_llm_client.chat.completions.create.return_value = _make_rewrite_completion(
            rewritten_query="văn hóa làng chài Hàm Ninh Phú Quốc truyền thống",
            reasoning="Added location context for better retrieval",
        )

        services = NodeServices(llm_client=mock_llm_client)
        configure_services(services)

        state = {
            "message": "văn hóa làng chài",
            "rewrite_count": 0,
            "session_id": "test-rewrite-001",
        }

        result = await rewrite_query_node(state)

        assert result["rewritten_query"] == "văn hóa làng chài Hàm Ninh Phú Quốc truyền thống"
        assert result["rewrite_count"] == 1
        mock_llm_client.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_llm_passthrough(self):
        """No LLM client → returns original message, rewrite_count unchanged."""
        services = NodeServices(llm_client=None)
        configure_services(services)

        state = {
            "message": "văn hóa làng chài",
            "rewrite_count": 2,
            "session_id": "test-rewrite-002",
        }

        result = await rewrite_query_node(state)

        assert result["rewritten_query"] == "văn hóa làng chài"
        assert result["rewrite_count"] == 2  # unchanged

    @pytest.mark.asyncio
    async def test_llm_failure_returns_original_message(
        self,
        mock_llm_client,
    ):
        """LLM raises generic exception → returns original message, rewrite_count incremented."""
        mock_llm_client.chat.completions.create.side_effect = Exception(
            "OpenAI API rate limit exceeded"
        )

        services = NodeServices(llm_client=mock_llm_client)
        configure_services(services)

        state = {
            "message": "lịch sử Hàm Ninh",
            "rewrite_count": 0,
            "session_id": "test-rewrite-003",
        }

        result = await rewrite_query_node(state)

        assert result["rewritten_query"] == "lịch sử Hàm Ninh"
        assert result["rewrite_count"] == 1

    @pytest.mark.asyncio
    async def test_llm_timeout_returns_original_message(
        self,
        mock_llm_client,
    ):
        """LLM raises TimeoutError → returns original message, rewrite_count incremented."""
        import asyncio

        mock_llm_client.chat.completions.create.side_effect = asyncio.TimeoutError(
            "LLM request timed out after 30s"
        )

        services = NodeServices(llm_client=mock_llm_client)
        configure_services(services)

        state = {
            "message": "đường đi đến Hàm Ninh",
            "rewrite_count": 1,
            "session_id": "test-rewrite-004",
        }

        result = await rewrite_query_node(state)

        assert result["rewritten_query"] == "đường đi đến Hàm Ninh"
        assert result["rewrite_count"] == 2

    @pytest.mark.asyncio
    async def test_rewrite_count_incremented_on_success(
        self,
        mock_llm_client,
    ):
        """Success path: rewrite_count goes from N to N+1."""
        mock_llm_client.chat.completions.create.return_value = _make_rewrite_completion(
            rewritten_query="improved query",
            reasoning="more specific",
        )

        services = NodeServices(llm_client=mock_llm_client)
        configure_services(services)

        # Start at rewrite_count=3
        state = {
            "message": "original query",
            "rewrite_count": 3,
            "session_id": "test-rewrite-005",
        }

        result = await rewrite_query_node(state)

        assert result["rewrite_count"] == 4
        assert result["rewritten_query"] == "improved query"

    @pytest.mark.asyncio
    async def test_rewrite_count_incremented_on_failure(
        self,
        mock_llm_client,
    ):
        """Failure path: rewrite_count goes from N to N+1."""
        mock_llm_client.chat.completions.create.side_effect = ConnectionError(
            "Network unreachable"
        )

        services = NodeServices(llm_client=mock_llm_client)
        configure_services(services)

        # Start at rewrite_count=5
        state = {
            "message": "failing query",
            "rewrite_count": 5,
            "session_id": "test-rewrite-006",
        }

        result = await rewrite_query_node(state)

        assert result["rewrite_count"] == 6
        assert result["rewritten_query"] == "failing query"
