import pytest

from app.models.rag import RAGChunk, RetrievalResult
from app.models.response import ChatResponse
from app.services.agent_service import AgentService, InMemoryAgentCheckpointer
from app.services.grounded_answer import detect_intent
from app.services.retriever import citation_from_chunk


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


@pytest.mark.asyncio
async def test_agent_answers_first_turn_with_citations(ham_ninh_chunk):
    retriever = FakeRetriever([ham_ninh_chunk])
    service = AgentService(
        retriever=retriever,
        llm_service=FakeLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
    )

    response = await service.answer(
        session_id="s-agent-1",
        message="Ham Ninh co gi dac biet?",
        language="vi",
    )

    assert response.session_id == "s-agent-1"
    assert response.message.startswith("LLM grounded:")
    assert response.fallback is False
    assert response.citations[0].source == "Ham Ninh Culture"


@pytest.mark.asyncio
async def test_agent_uses_prior_turn_for_follow_up_retrieval(ham_ninh_chunk):
    retriever = FakeRetriever([ham_ninh_chunk])
    service = AgentService(
        retriever=retriever,
        llm_service=FakeLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
    )

    await service.answer(session_id="s-agent-2", message="Ke ve Ham Ninh", language="vi")
    await service.answer(session_id="s-agent-2", message="No co gi ngon?", language="vi")

    assert retriever.queries[0] == "Ke ve Ham Ninh"
    assert retriever.queries[1] == "Ke ve Ham Ninh\nNo co gi ngon?"


@pytest.mark.asyncio
async def test_agent_falls_back_when_llm_unavailable(ham_ninh_chunk):
    service = AgentService(
        retriever=FakeRetriever([ham_ninh_chunk]),
        llm_service=FailingLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
    )

    response = await service.answer(
        session_id="s-agent-3",
        message="Ham Ninh co gi dac biet?",
        language="vi",
    )

    assert response.fallback is True
    assert response.citations
    assert "Ham Ninh" in response.message


@pytest.mark.asyncio
async def test_agent_returns_honest_no_evidence_when_retrieval_empty(ham_ninh_chunk):
    service = AgentService(
        retriever=FakeRetriever([ham_ninh_chunk]),
        llm_service=FailingLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
    )

    response = await service.answer(
        session_id="s-agent-4",
        message="khong-co-du-lieu",
        language="en",
    )

    assert response.fallback is True
    assert response.citations == []
    assert "do not have sufficient information" in response.message


@pytest.mark.asyncio
async def test_agent_stream_yields_tokens_citations_and_done(ham_ninh_chunk):
    service = AgentService(
        retriever=FakeRetriever([ham_ninh_chunk]),
        llm_service=FakeLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
    )

    events = [
        event
        async for event in service.stream(
            session_id="s-agent-5",
            message="Stream Ham Ninh",
            language="vi",
        )
    ]

    assert events[:2] == ["LLM ", "stream"]
    assert events[-2].startswith("[CITATIONS]")
    assert events[-1] == "[DONE]"
