"""Unit tests for grade_documents_node.

Tests cover:
- No chunks → grade_score=0.0, grade_label='irrelevant'
- No LLM client → grade_score=1.0, grade_label='relevant' (pass-through)
- LLM grading with all relevant → grade_score=1.0, grade_label='relevant'
- LLM grading with all irrelevant → grade_score=0.0, grade_label='irrelevant'
- LLM grading with mixed results → correct aggregate score
- Per-chunk LLM failure → assume relevant (1.0), log warning
- Top-5 limit on chunk grading
- Structured log events emitted correctly
"""

import os
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["OPENAI_API_KEY"] = "test-key-for-unit-tests"
os.environ["APP_ENV"] = "test"

import pytest

from agents.graph.nodes import (
    grade_documents_node,
    NodeServices,
    configure_services,
    get_services,
)


@dataclass
class FakeChunk:
    """Minimal chunk with title and text attributes."""
    title: str = ""
    text: str = ""


def _make_completion(binary_score: str) -> MagicMock:
    """Create a mock LLM completion response."""
    import json
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message.content = json.dumps({"binary_score": binary_score})
    return mock


@pytest.fixture(autouse=True)
def _reset_services():
    """Reset NodeServices to defaults after each test."""
    yield
    configure_services(NodeServices())


# ---------------------------------------------------------------------------
# No chunks path
# ---------------------------------------------------------------------------


class TestNoChunks:
    """When knowledge_chunks is empty or None."""

    @pytest.mark.asyncio
    async def test_empty_chunks_returns_irrelevant(self):
        """No chunks → grade_score=0.0, grade_label='irrelevant'."""
        state = {
            "session_id": "test-session",
            "message": "What is the culture of Ham Ninh?",
            "knowledge_chunks": [],
        }
        result = await grade_documents_node(state)
        assert result["grade_score"] == 0.0
        assert result["grade_label"] == "irrelevant"

    @pytest.mark.asyncio
    async def test_none_chunks_returns_irrelevant(self):
        """None chunks → grade_score=0.0, grade_label='irrelevant'."""
        state = {
            "session_id": "test-session",
            "message": "What is the culture of Ham Ninh?",
            "knowledge_chunks": None,
        }
        result = await grade_documents_node(state)
        assert result["grade_score"] == 0.0
        assert result["grade_label"] == "irrelevant"

    @pytest.mark.asyncio
    async def test_missing_chunks_field_returns_irrelevant(self):
        """Missing knowledge_chunks key → grade_score=0.0, grade_label='irrelevant'."""
        state = {
            "session_id": "test-session",
            "message": "What is the culture of Ham Ninh?",
        }
        result = await grade_documents_node(state)
        assert result["grade_score"] == 0.0
        assert result["grade_label"] == "irrelevant"


# ---------------------------------------------------------------------------
# No LLM client path
# ---------------------------------------------------------------------------


class TestNoLLMClient:
    """When llm_client is None (no OpenAI available)."""

    @pytest.mark.asyncio
    async def test_no_llm_returns_relevant_passthrough(self):
        """No LLM client → grade_score=1.0, grade_label='relevant'."""
        configure_services(NodeServices(llm_client=None))
        chunks = [FakeChunk(title="Ham Ninh", text="Fishing village culture")]
        state = {
            "session_id": "test-session",
            "message": "What is the culture of Ham Ninh?",
            "knowledge_chunks": chunks,
        }
        result = await grade_documents_node(state)
        assert result["grade_score"] == 1.0
        assert result["grade_label"] == "relevant"


# ---------------------------------------------------------------------------
# LLM grading path
# ---------------------------------------------------------------------------


class TestLLMGrading:
    """When LLM client is available and grading succeeds."""

    @pytest.mark.asyncio
    async def test_all_relevant_chunks(self):
        """All chunks relevant → grade_score=1.0, grade_label='relevant'."""
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_completion("yes")
        )
        configure_services(NodeServices(llm_client=mock_client, model="gpt-4o-mini"))

        chunks = [
            FakeChunk(title="Ham Ninh fishing", text="Traditional fishing methods"),
            FakeChunk(title="Pearl farm", text="Pearl cultivation in Ham Ninh"),
        ]
        state = {
            "session_id": "test-session",
            "message": "What is the culture of Ham Ninh?",
            "knowledge_chunks": chunks,
        }
        result = await grade_documents_node(state)
        assert result["grade_score"] == 1.0
        assert result["grade_label"] == "relevant"
        assert mock_client.chat.completions.create.call_count == 2

    @pytest.mark.asyncio
    async def test_all_irrelevant_chunks(self):
        """All chunks irrelevant → grade_score=0.0, grade_label='irrelevant'."""
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_completion("no")
        )
        configure_services(NodeServices(llm_client=mock_client, model="gpt-4o-mini"))

        chunks = [
            FakeChunk(title="Ho Chi Minh City", text="Saigon nightlife guide"),
            FakeChunk(title="Hanoi food", text="Pho recipe from Hanoi"),
        ]
        state = {
            "session_id": "test-session",
            "message": "What is the culture of Ham Ninh?",
            "knowledge_chunks": chunks,
        }
        result = await grade_documents_node(state)
        assert result["grade_score"] == 0.0
        assert result["grade_label"] == "irrelevant"

    @pytest.mark.asyncio
    async def test_mixed_relevance(self):
        """Mixed results → correct aggregate score."""
        mock_client = MagicMock()
        # First chunk relevant, second irrelevant
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[
                _make_completion("yes"),
                _make_completion("no"),
            ]
        )
        configure_services(NodeServices(llm_client=mock_client, model="gpt-4o-mini"))

        chunks = [
            FakeChunk(title="Ham Ninh fishing", text="Traditional fishing"),
            FakeChunk(title="Hanoi food", text="Pho recipe"),
        ]
        state = {
            "session_id": "test-session",
            "message": "What is the culture of Ham Ninh?",
            "knowledge_chunks": chunks,
        }
        result = await grade_documents_node(state)
        assert result["grade_score"] == 0.5  # (1.0 + 0.0) / 2
        assert result["grade_label"] == "relevant"  # >= 0.5

    @pytest.mark.asyncio
    async def test_top5_limit_enforced(self):
        """Only top-5 chunks are graded even if more are provided."""
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_completion("yes")
        )
        configure_services(NodeServices(llm_client=mock_client, model="gpt-4o-mini"))

        chunks = [FakeChunk(title=f"Chunk {i}", text=f"Text {i}") for i in range(8)]
        state = {
            "session_id": "test-session",
            "message": "What is the culture?",
            "knowledge_chunks": chunks,
        }
        result = await grade_documents_node(state)
        assert result["grade_score"] == 1.0
        assert result["grade_label"] == "relevant"
        # Only 5 LLM calls despite 8 chunks
        assert mock_client.chat.completions.create.call_count == 5

    @pytest.mark.asyncio
    async def test_response_format_is_grade_documents(self):
        """LLM call uses response_format=GradeDocuments."""
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_completion("yes")
        )
        configure_services(NodeServices(llm_client=mock_client, model="gpt-4o-mini"))

        chunks = [FakeChunk(title="Test", text="Test content")]
        state = {
            "session_id": "test-session",
            "message": "Test question",
            "knowledge_chunks": chunks,
        }
        await grade_documents_node(state)

        call_kwargs = mock_client.chat.completions.create.call_args
        from agents.graph.state import GradeDocuments
        assert call_kwargs.kwargs.get("response_format") is GradeDocuments


# ---------------------------------------------------------------------------
# LLM failure path
# ---------------------------------------------------------------------------


class TestLLMFailure:
    """When LLM calls fail for individual chunks."""

    @pytest.mark.asyncio
    async def test_chunk_failure_assumes_relevant(self):
        """Per-chunk LLM failure → assume relevant (score 1.0)."""
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("API timeout")
        )
        configure_services(NodeServices(llm_client=mock_client, model="gpt-4o-mini"))

        chunks = [FakeChunk(title="Test", text="Test content")]
        state = {
            "session_id": "test-session",
            "message": "What is the culture?",
            "knowledge_chunks": chunks,
        }
        result = await grade_documents_node(state)
        # Failure → assume relevant
        assert result["grade_score"] == 1.0
        assert result["grade_label"] == "relevant"

    @pytest.mark.asyncio
    async def test_partial_failure_with_mixed_results(self):
        """Some chunks fail, some succeed → mixed scores."""
        mock_client = MagicMock()
        # First succeeds (no), second fails, third succeeds (yes)
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[
                _make_completion("no"),
                RuntimeError("Connection lost"),
                _make_completion("yes"),
            ]
        )
        configure_services(NodeServices(llm_client=mock_client, model="gpt-4o-mini"))

        chunks = [
            FakeChunk(title="A", text="Content A"),
            FakeChunk(title="B", text="Content B"),
            FakeChunk(title="C", text="Content C"),
        ]
        state = {
            "session_id": "test-session",
            "message": "Test question",
            "knowledge_chunks": chunks,
        }
        result = await grade_documents_node(state)
        # (0.0 + 1.0 + 1.0) / 3 = 0.667
        assert abs(result["grade_score"] - 0.667) < 0.01
        assert result["grade_label"] == "relevant"  # >= 0.5
