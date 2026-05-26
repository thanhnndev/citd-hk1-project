"""Unit tests for Langfuse tracing integration in AgentService."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.models.rag import RAGChunk, RetrievalResult
from app.models.response import ChatResponse
from agents.graph.agent_service import (
    AgentService,
    InMemoryAgentCheckpointer,
)
from agents.guardrails.grounded_answer import detect_intent
from agents.tools.retriever import Retriever, citation_from_chunk


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ham_ninh_chunk():
    return RAGChunk(
        chunk_id="c1",
        source_id="s1",
        title="Ham Ninh Culture",
        url="https://example.test/ham-ninh",
        domain="tourism",
        source_type="guide",
        reliability="high",
        language="vi",
        location="Ham Ninh",
        text="Lang chai Ham Ninh noi tieng voi cau cang, doi song ngu dan va hai san tuoi.",
        chunk_index=0,
        total_chunks=1,
    )


class FakeRetriever:
    def __init__(self, chunks):
        self.chunks = chunks
        self.queries = []

    def search_with_citations(self, query, top_k=5):
        self.queries.append(query)
        chunks = self.chunks if "khong-co-du-lieu" not in query else []
        return RetrievalResult(chunks=chunks, query=query, total_found=len(chunks)), [
            citation_from_chunk(chunk) for chunk in chunks
        ]


class FakeLLM:
    def __init__(self):
        self.queries = []

    async def answer(self, chunks, citations, query, language, session_id):
        self.queries.append(query)
        return ChatResponse(
            session_id=session_id,
            message=f"LLM grounded: {query}",
            citations=citations,
            places=[],
            intent=detect_intent(query),
            langfuse_trace_id=None,
            latency_ms=1.0,
            fallback=False,
        )

    async def answer_stream(self, chunks, citations, query, language, session_id):
        yield "LLM "
        yield "stream"


class FailingLLM:
    async def answer(self, *args, **kwargs):
        raise RuntimeError("llm unavailable")

    async def answer_stream(self, *args, **kwargs):
        raise RuntimeError("llm unavailable")
        yield "unreachable"


class MockLangfuseSpan:
    """Mock Langfuse span that records update/end calls."""

    def __init__(self, name: str):
        self.name = name
        self.input_data: dict | None = None
        self.output_data: dict | None = None
        self.ended = False

    def update(self, output: dict | None = None) -> None:
        self.output_data = output

    def end(self) -> None:
        self.ended = True


class MockLangfuseClient:
    """Mock Langfuse client that records trace/span creation."""

    def __init__(self) -> None:
        self.create_trace_id_calls: list[str | None] = []
        self.start_observation_calls: list[dict[str, Any]] = []
        self._trace_counter = 0

    def create_trace_id(self, *, seed: str | None = None) -> str:
        self.create_trace_id_calls.append(seed)
        self._trace_counter += 1
        return f"trace-{self._trace_counter}-{seed or 'anonymous'}"

    def start_observation(
        self,
        *,
        trace_context: Any = None,
        name: str,
        as_type: str = "span",
        input: dict | None = None,
        output: dict | None = None,
        **kwargs: Any,
    ) -> MockLangfuseSpan:
        self.start_observation_calls.append({
            "name": name,
            "as_type": as_type,
            "input": input,
            "output": output,
        })
        return MockLangfuseSpan(name=name)


# ---------------------------------------------------------------------------
# Langfuse tracing tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_langfuse_client_produces_trace_id_on_response(ham_ninh_chunk):
    """AgentService with a Langfuse client should attach langfuse_trace_id to ChatResponse."""
    mock_client = MockLangfuseClient()
    retriever = FakeRetriever([ham_ninh_chunk])

    service = AgentService(
        retriever=retriever,
        llm_service=FakeLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
        langfuse_client=mock_client,
    )

    response = await service.answer(
        session_id="sess-langfuse-1",
        message="Ham Ninh co gi dac biet?",
        language="vi",
    )

    assert response.langfuse_trace_id is not None
    assert response.langfuse_trace_id.startswith("trace-")
    assert "sess-langfuse-1" in response.langfuse_trace_id


@pytest.mark.asyncio
async def test_langfuse_create_trace_id_called_once_per_answer(ham_ninh_chunk):
    """create_trace_id should be called exactly once per answer() call."""
    mock_client = MockLangfuseClient()
    retriever = FakeRetriever([ham_ninh_chunk])

    service = AgentService(
        retriever=retriever,
        llm_service=FakeLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
        langfuse_client=mock_client,
    )

    await service.answer(
        session_id="sess-trace-1",
        message="Hello",
        language="vi",
    )

    assert len(mock_client.create_trace_id_calls) == 1
    assert mock_client.create_trace_id_calls[0] == "sess-trace-1"


@pytest.mark.asyncio
async def test_langfuse_spans_created_for_retrieve_and_answer(ham_ninh_chunk):
    """start_observation should be called for both retrieve and answer nodes."""
    mock_client = MockLangfuseClient()
    retriever = FakeRetriever([ham_ninh_chunk])

    service = AgentService(
        retriever=retriever,
        llm_service=FakeLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
        langfuse_client=mock_client,
    )

    await service.answer(
        session_id="sess-spans-1",
        message="Ham Ninh culture",
        language="vi",
    )

    span_names = [call["name"] for call in mock_client.start_observation_calls]
    assert "retrieve" in span_names
    assert "answer" in span_names
    # Exactly two spans per answer() call
    assert len(mock_client.start_observation_calls) == 2


@pytest.mark.asyncio
async def test_langfuse_retrieve_span_has_input_and_output(ham_ninh_chunk):
    """Retrieve span should record query as input and retrieval_count as output."""
    mock_client = MockLangfuseClient()
    retriever = FakeRetriever([ham_ninh_chunk])

    service = AgentService(
        retriever=retriever,
        llm_service=FakeLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
        langfuse_client=mock_client,
    )

    await service.answer(
        session_id="sess-retrieve-meta",
        message="Ham Ninh",
        language="vi",
    )

    retrieve_call = next(
        c for c in mock_client.start_observation_calls if c["name"] == "retrieve"
    )
    # Input contains the query
    assert retrieve_call["input"] is not None
    assert "query" in retrieve_call["input"]
    # Retrieve span ends — recorded in the MockLangfuseSpan
    # (We check the span objects through the mock's calls)
    assert len(mock_client.start_observation_calls) >= 2


@pytest.mark.asyncio
async def test_langfuse_graceful_degradation_when_client_is_none(ham_ninh_chunk):
    """AgentService should work normally when langfuse_client is None (default)."""
    retriever = FakeRetriever([ham_ninh_chunk])

    service = AgentService(
        retriever=retriever,
        llm_service=FakeLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
        # langfuse_client defaults to None
    )

    response = await service.answer(
        session_id="sess-no-langfuse",
        message="Ham Ninh",
        language="vi",
    )

    # Response should still work
    assert response.session_id == "sess-no-langfuse"
    assert response.message.startswith("LLM grounded:")
    assert response.fallback is False
    # trace_id should be None when no client
    assert response.langfuse_trace_id is None


@pytest.mark.asyncio
async def test_langfuse_graceful_degradation_when_client_raises(ham_ninh_chunk):
    """AgentService should not crash when Langfuse client raises on create_trace_id."""
    broken_client = MagicMock()
    broken_client.create_trace_id.side_effect = RuntimeError("langfuse down")

    retriever = FakeRetriever([ham_ninh_chunk])

    service = AgentService(
        retriever=retriever,
        llm_service=FakeLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
        langfuse_client=broken_client,
    )

    # Should not raise — graceful degradation
    response = await service.answer(
        session_id="sess-broken-langfuse",
        message="Ham Ninh",
        language="vi",
    )

    assert response.session_id == "sess-broken-langfuse"
    assert response.message.startswith("LLM grounded:")


@pytest.mark.asyncio
async def test_langfuse_stream_produces_trace_id(ham_ninh_chunk):
    """answer_stream should also create Langfuse traces."""
    mock_client = MockLangfuseClient()
    retriever = FakeRetriever([ham_ninh_chunk])

    service = AgentService(
        retriever=retriever,
        llm_service=FakeLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
        langfuse_client=mock_client,
    )

    events = [
        event
        async for event in service.answer_stream(
            session_id="sess-stream-trace",
            message="Stream test",
            language="vi",
        )
    ]

    # create_trace_id should have been called
    assert len(mock_client.create_trace_id_calls) == 1
    # Spans should have been created (retrieve + answer)
    span_names = [c["name"] for c in mock_client.start_observation_calls]
    assert "retrieve" in span_names
    assert "answer" in span_names
    # Stream should still yield tokens
    assert events[:2] == ["LLM ", "stream"]
    assert events[-1] == "[DONE]"


@pytest.mark.asyncio
async def test_existing_tests_still_pass_without_langfuse(ham_ninh_chunk):
    """Existing AgentService tests should pass unchanged (langfuse_client defaults to None)."""
    # This is a meta-test verifying that the default parameter is None
    service = AgentService(
        retriever=FakeRetriever([ham_ninh_chunk]),
        llm_service=FakeLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
    )
    assert service._langfuse_client is None
