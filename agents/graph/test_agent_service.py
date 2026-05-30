"""Behavior tests for the LangGraph-style AgentService."""

from __future__ import annotations

from app.models.rag import RAGChunk, RetrievalResult
from agents.graph.agent_service import AgentService, InMemoryAgentCheckpointer
from agents.tools.retriever import citation_from_chunk
import pytest

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
        return RetrievalResult(chunks=chunks, query=query, total_found=len(chunks)), [citation_from_chunk(chunk) for chunk in chunks]

@pytest.mark.asyncio
async def test_greeting_does_not_retrieve(ham_ninh_chunk):
    retriever = FakeRetriever([ham_ninh_chunk])
    service = AgentService(retriever=retriever, checkpointer=InMemoryAgentCheckpointer(), checkpoint_mode="test")

    response = await service.answer(session_id="s-greeting", message="chào bạn", language="vi")

    assert response.intent == "conversational"
    assert response.citations == []
    assert retriever.queries == []

@pytest.mark.asyncio
async def test_capability_followup_examples_do_not_retrieve(ham_ninh_chunk):
    retriever = FakeRetriever([ham_ninh_chunk])
    service = AgentService(retriever=retriever, checkpointer=InMemoryAgentCheckpointer(), checkpoint_mode="test")

    first = await service.answer(session_id="s-help", message="bạn giúp được gì", language="vi")
    second = await service.answer(session_id="s-help", message="ví dụ cụ thể hơn đi", language="vi")

    assert "4 nhóm" in first.message
    assert "Ví dụ cụ thể" in second.message
    assert second.citations == []
    assert retriever.queries == []

@pytest.mark.asyncio
async def test_bare_followup_uses_history_without_retrieval(ham_ninh_chunk):
    retriever = FakeRetriever([ham_ninh_chunk])
    service = AgentService(retriever=retriever, checkpointer=InMemoryAgentCheckpointer(), checkpoint_mode="test")

    await service.answer(session_id="s-follow", message="bạn giúp được gì", language="vi")
    response = await service.answer(session_id="s-follow", message="?", language="vi")

    assert response.intent == "conversational"
    assert response.citations == []
    assert "4 nhóm" in response.message or "Ví dụ" in response.message
    assert retriever.queries == []

@pytest.mark.asyncio
async def test_place_capability_question_clarifies_without_rag(ham_ninh_chunk):
    retriever = FakeRetriever([ham_ninh_chunk])
    service = AgentService(retriever=retriever, checkpointer=InMemoryAgentCheckpointer(), checkpoint_mode="test")

    response = await service.answer(session_id="s-place-cap", message="kiếm khách sạn được không?", language="vi")

    assert response.intent == "conversational"
    assert response.citations == []
    assert "ngân sách" in response.message or "loại" in response.message
    assert retriever.queries == []

@pytest.mark.asyncio
async def test_ambiguous_route_clarifies_without_rag(ham_ninh_chunk):
    retriever = FakeRetriever([ham_ninh_chunk])
    service = AgentService(retriever=retriever, checkpointer=InMemoryAgentCheckpointer(), checkpoint_mode="test")

    response = await service.answer(session_id="s-route", message="tìm đường thế nào?", language="vi")

    assert response.intent == "clarification"
    assert response.citations == []
    assert "điểm" in response.message or "rõ" in response.message
    assert retriever.queries == []

@pytest.mark.asyncio
async def test_knowledge_query_is_only_path_that_returns_citations(ham_ninh_chunk):
    retriever = FakeRetriever([ham_ninh_chunk])
    service = AgentService(retriever=retriever, checkpointer=InMemoryAgentCheckpointer(), checkpoint_mode="test")

    response = await service.answer(session_id="s-knowledge", message="Làng chài Hàm Ninh có gì đặc biệt?", language="vi")

    assert response.intent == "cultural_query"
    assert response.citations
    assert retriever.queries == ["Làng chài Hàm Ninh có gì đặc biệt?"]

@pytest.mark.asyncio
async def test_stream_direct_answer_has_no_citations_marker(ham_ninh_chunk):
    retriever = FakeRetriever([ham_ninh_chunk])
    service = AgentService(retriever=retriever, checkpointer=InMemoryAgentCheckpointer(), checkpoint_mode="test")

    events = [event async for event in service.answer_stream(session_id="s-stream", message="chào bạn", language="vi")]

    assert any("Chào bạn" in event for event in events)
    assert not any(event.startswith("[CITATIONS]") for event in events)
    assert retriever.queries == []
