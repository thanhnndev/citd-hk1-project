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

    assert response.intent == "followup_history"
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

def test_extract_suggestions_strips_tag_and_populates_list():
    from agents.graph.agent_service import _extract_suggestions
    text = "Chào bạn! [SUGGESTIONS] Gợi ý 1 | Gợi ý 2 | Gợi ý 3"
    msg, sug = _extract_suggestions(text)
    assert msg == "Chào bạn!"
    assert sug == ["Gợi ý 1", "Gợi ý 2", "Gợi ý 3"]

def test_response_from_state_gracefully_falls_back_to_defaults(ham_ninh_chunk):
    retriever = FakeRetriever([ham_ninh_chunk])
    service = AgentService(retriever=retriever, checkpointer=InMemoryAgentCheckpointer(), checkpoint_mode="test")
    state = {
        "session_id": "test-fallback",
        "language": "vi",
        "response_text": "Xin chào!",
        "places": [],
        "citations": [],
    }
    response = service._response_from_state(state, 0)
    assert response.suggestions == ["Bạn còn làm được gì?", "Kể về ẩm thực địa phương"]

def test_descriptive_new_request_bypasses_clarification_loop():
    from agents.graph.agent_service import resolve_followup_decision, FollowUpContext, PLACE_RECOMMENDATION_INTENT
    
    ctx = FollowUpContext(
        session_id="test-bypass",
        intent=PLACE_RECOMMENDATION_INTENT,
        place_ids=["place_1", "place_2"],
        place_display_names=["ANBA COFFEE", "Lotus Home & Cafe"],
    )
    
    # Message is a descriptive new place request that does not overlap distinctively with previous names
    message = "quán cf view đẹp giá dưới 50k"
    decision = resolve_followup_decision(message, ctx, history=[{"role": "user", "content": "hello"}])
    assert decision == "insufficient_context"

    # Message is an abbreviated descriptive new request without standard Vietnamese prefixes
    message_abbr = "cf view đẹp giá dưới 50k"
    decision_abbr = resolve_followup_decision(message_abbr, ctx, history=[{"role": "user", "content": "hello"}])
    assert decision_abbr == "insufficient_context"


def test_explicit_new_place_search_beats_generic_prior_place_overlap():
    from agents.graph.agent_service import resolve_followup_decision, FollowUpContext, PLACE_RECOMMENDATION_INTENT

    ctx = FollowUpContext(
        session_id="test-seafood-overlap",
        intent=PLACE_RECOMMENDATION_INTENT,
        place_ids=["place_1"],
        place_display_names=["Quán Hải Sản Thiện"],
        score_breakdown_keys=["final_score"],
    )

    decision = resolve_followup_decision(
        "Tìm nhà hàng hải sản địa phương",
        ctx,
        history=[{"role": "assistant", "content": "Mình tìm được Quán Hải Sản Thiện."}],
    )
    assert decision == "insufficient_context"


def test_non_search_place_name_followup_still_uses_structured_context():
    from agents.graph.agent_service import resolve_followup_decision, FollowUpContext, PLACE_RECOMMENDATION_INTENT

    ctx = FollowUpContext(
        session_id="test-seafood-followup",
        intent=PLACE_RECOMMENDATION_INTENT,
        place_ids=["place_1"],
        place_display_names=["Quán Hải Sản Thiện"],
    )

    decision = resolve_followup_decision("Hải Sản Thiện có ngon không?", ctx)
    assert decision == "structured_context"

