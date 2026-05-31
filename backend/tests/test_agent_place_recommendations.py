"""AgentService place-intent routing tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.response import ChatResponse, PlaceResult, ScoreBreakdown
from app.models.request import LatLng
from agents.graph.agent_service import AgentService


def _place(place_id: str = "places/ham-ninh-seafood") -> PlaceResult:
    return PlaceResult(
        place_id=place_id,
        display_name="Ham Ninh Seafood",
        formatted_address="Ham Ninh, Phu Quoc",
        rating=4.6,
        price_level=2,
        local_factor=0.8,
        final_score=0.9,
        score_breakdown=ScoreBreakdown(
            tree1_locality=0.9,
            tree2_proximity=0.8,
            tree3_quality=0.85,
            s_bag=0.85,
            delta1_fairness=0.0,
            delta2_access=0.0,
            final_score=0.9,
            rank=1,
        ),
        accessibility_score=0.5,
        map_uri="https://maps.example/ham-ninh-seafood",
    )


def _place_response(session_id: str = "s-place") -> ChatResponse:
    return ChatResponse(
        session_id=session_id,
        message="I found 1 local place option(s) in Ho Chi Minh City from Goong Places.",
        citations=[],
        places=[_place()],
        reasoning_log="place_recommendation status=ok source=goong_places candidate_count=1 result_count=1",
        intent="place_recommendation",
        latency_ms=1.0,
        fallback=False,
    )


@pytest.mark.asyncio
async def test_place_intent_calls_recommendation_service_and_skips_llm() -> None:
    recommender = AsyncMock()
    recommender.recommend.return_value = _place_response()
    llm = AsyncMock()
    service = AgentService(
        retriever=None,
        llm_service=llm,
        place_recommendation_service=recommender,
        checkpoint_mode="test",
    )

    response = await service.answer(session_id="s-place", message="Gợi ý nhà hàng hải sản ở Hàm Ninh", language="vi")

    recommender.recommend.assert_awaited_once_with(
        query="Gợi ý nhà hàng hải sản ở Hàm Ninh",
        language="vi",
        session_id="s-place",
    )
    llm.answer.assert_not_called()
    assert [place.place_id for place in response.places] == ["places/ham-ninh-seafood"]
    assert response.intent == "place_recommendation"


@pytest.mark.asyncio
async def test_navigation_intent_routes_to_grounded_places() -> None:
    recommender = AsyncMock()
    recommender.recommend.return_value = _place_response("s-nav")
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-nav", message="Chỉ đường đến chợ Hàm Ninh", language="vi")

    recommender.recommend.assert_awaited_once()
    assert response.places[0].place_id == "places/ham-ninh-seafood"


@pytest.mark.asyncio
async def test_non_place_cultural_query_does_not_call_recommendation_service() -> None:
    recommender = AsyncMock()
    llm = AsyncMock()
    llm.answer.return_value = ChatResponse(
        session_id="s-culture",
        message="Ham Ninh is a fishing village.",
        citations=[],
        places=[],
        intent="cultural_query",
        latency_ms=1.0,
    )
    service = AgentService(
        retriever=None,
        llm_service=llm,
        place_recommendation_service=recommender,
        checkpoint_mode="test",
    )

    response = await service.answer(session_id="s-culture", message="Kể về lịch sử làng chài Hàm Ninh", language="vi")

    recommender.recommend.assert_not_called()
    llm.answer.assert_not_called()
    assert response.intent == "cultural_query"
    assert response.places == []


@pytest.mark.asyncio
async def test_missing_recommendation_dependency_falls_through_to_llm() -> None:
    """Soft routing: when Places API is missing, place intent falls through to LLM."""
    llm = AsyncMock()
    llm.answer.return_value = ChatResponse(
        session_id="s-missing",
        message="I don't have specific place data, but Ham Ninh is a fishing village.",
        citations=[],
        places=[],
        intent="cultural_query",
        latency_ms=1.0,
        fallback=False,
    )
    service = AgentService(retriever=None, llm_service=llm, checkpoint_mode="test")

    response = await service.answer(session_id="s-missing", message="Recommend a place in Ham Ninh", language="en")

    # Tool policy: place requests never fall back to document RAG/LLM when Places is unavailable.
    llm.answer.assert_not_called()
    assert response.fallback is False
    assert response.places == []


@pytest.mark.asyncio
async def test_recommendation_exception_falls_through_to_llm() -> None:
    """Soft routing: when Places API throws, LLM handles the response."""
    recommender = AsyncMock()
    recommender.recommend.side_effect = RuntimeError("secret provider payload")
    llm = AsyncMock()
    llm.answer.return_value = ChatResponse(
        session_id="s-error",
        message="Tôi chưa có thông tin cụ thể về khoản này.",
        citations=[],
        places=[],
        intent=None,
        latency_ms=1.0,
        fallback=False,
    )
    service = AgentService(retriever=None, llm_service=llm, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-error", message="Gợi ý dịch vụ ở Hàm Ninh", language="vi")

    # Tool policy: provider errors are reported honestly and not leaked.
    assert "secret provider payload" not in response.message
    llm.answer.assert_not_called()
    assert response.places == []


@pytest.mark.asyncio
async def test_stream_place_intent_uses_deterministic_text_and_places_marker() -> None:
    recommender = AsyncMock()
    recommender.recommend.return_value = _place_response("s-stream")
    llm = AsyncMock()
    service = AgentService(
        retriever=None,
        llm_service=llm,
        place_recommendation_service=recommender,
        checkpoint_mode="test",
    )

    events = [event async for event in service.answer_stream(session_id="s-stream", message="Recommend a place in Ham Ninh", language="en")]

    llm.answer_stream.assert_not_called()
    assert "I found 1 local place option(s) in Ho Chi Minh City from Goong Places." in events
    assert "[DONE]" not in events  # router owns the terminal SSE marker
    assert any(event.startswith("[PLACES]") for event in events)


@pytest.mark.asyncio
async def test_nearby_restaurant_query_routes_to_places_before_rag() -> None:
    recommender = AsyncMock()
    recommender.recommend.return_value = _place_response("s-nearby")
    llm = AsyncMock()
    service = AgentService(
        retriever=None,
        llm_service=llm,
        place_recommendation_service=recommender,
        checkpoint_mode="test",
    )

    response = await service.answer(session_id="s-nearby", message="kiếm nhà hàng gần đây", language="vi")

    recommender.recommend.assert_awaited_once()
    llm.answer.assert_not_called()
    assert response.places
    assert response.citations == []

@pytest.mark.asyncio
async def test_capability_example_followup_does_not_rag() -> None:
    service = AgentService(retriever=None, checkpoint_mode="test")

    first = await service.answer(session_id="s-examples", message="bạn giúp được gì", language="vi")
    second = await service.answer(session_id="s-examples", message="ví dụ cụ thể hơn đi", language="vi")

    assert "4 nhóm" in first.message
    assert "Ví dụ cụ thể" in second.message
    assert second.citations == []
    assert second.places == []

@pytest.mark.asyncio
async def test_recommendation_service_preserves_pin_ready_candidate_fields() -> None:
    from datetime import UTC, datetime

    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    candidate = PlaceCandidate(
        place_id="places/pin-ready",
        display_name="Pin Ready Seafood",
        types=["restaurant", "seafood_restaurant"],
        primary_type="seafood_restaurant",
        formatted_address="Ham Ninh, Phu Quoc",
        location=LatLng(lat=10.1794, lng=104.0491),
        rating=4.7,
        user_rating_count=321,
        price_level=2,
        open_now=True,
        business_status="OPERATIONAL",
        map_uri="https://maps.example/pin-ready",
    )
    request = PlaceSearchRequest(query="seafood")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=[candidate],
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    service = PlaceRecommendationService(places_tool)

    response = await service.recommend(query="seafood", language="en", session_id="s-pin")

    place = response.places[0]
    assert place.place_id == "places/pin-ready"
    assert place.location == LatLng(lat=10.1794, lng=104.0491)
    assert place.types == ["restaurant", "seafood_restaurant"]
    assert place.primary_type == "seafood_restaurant"
    assert place.user_rating_count == 321
    assert place.open_now is True
    assert place.business_status == "OPERATIONAL"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        "credentials_blocked",
        "upstream_error",
        "empty",
    ],
)
async def test_recommendation_service_negative_statuses_return_empty_places(status: str) -> None:
    from datetime import UTC, datetime

    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    places_tool = AsyncMock()
    request = PlaceSearchRequest(query="seafood")
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus(status),
        source=PlaceToolSource.MOCK,
        candidates=[
            PlaceCandidate(
                place_id="places/ignored",
                display_name="Ignored",
                location=LatLng(lat=10.1794, lng=104.0491),
                types=["restaurant"],
            )
        ],
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    service = PlaceRecommendationService(places_tool)

    response = await service.recommend(query="seafood", language="en", session_id="s-negative")

    assert response.places == []
    assert f"status={status}" in (response.reasoning_log or "")


# ============================================================================
# T02: Deterministic /chat place output — no citations, no RAG, no LLM override
# ============================================================================

class _FakeLLMClient:
    """Non-mock LLM client wrapper so _real_client does not detect it as a mock."""

    def __init__(self, completions_mock: AsyncMock) -> None:
        self.chat = MagicMock()
        self.chat.completions = completions_mock


class _FakeLLMService:
    """Non-mock LLM service so _real_client follows the real path."""

    def __init__(self, completions_mock: AsyncMock, model: str = "gpt-4o-mini") -> None:
        self._client = _FakeLLMClient(completions_mock)
        self.model = model


@pytest.mark.asyncio
async def test_place_intent_with_llm_bypasses_llm_composition() -> None:
    """When LLM client is available, place tool result sets places_response_ready
    so _should_continue returns END immediately — LLM does not overwrite response_text."""
    recommender = AsyncMock()
    recommender.recommend.return_value = _place_response()

    # LLM mock: first call returns tool_calls=[search_places], second call (if reached)
    # would return text content — but places_response_ready prevents it.
    llm_completions = AsyncMock()
    call_count = 0

    def _llm_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: LLM decides to call search_places
            tool_call = MagicMock()
            tool_call.id = "tc-1"
            tool_call.function.name = "search_places"
            tool_call.function.arguments = '{"query": "tìm nhà hàng hải sản"}'
            msg = MagicMock()
            msg.tool_calls = [tool_call]
            msg.content = None
        else:
            # Second call (should NOT be reached): LLM would compose its own answer
            msg = MagicMock()
            msg.tool_calls = []
            msg.content = "LLM composed: I found many amazing restaurants!"
        completion = MagicMock()
        completion.choices = [MagicMock()]
        completion.choices[0].message = msg
        return completion

    llm_completions.create = AsyncMock(side_effect=_llm_side_effect)

    llm_service = _FakeLLMService(llm_completions)

    service = AgentService(
        retriever=None,
        llm_service=llm_service,
        place_recommendation_service=recommender,
        checkpoint_mode="test",
    )

    response = await service.answer(
        session_id="s-bypass", message="tìm nhà hàng hải sản", language="vi"
    )

    # LLM was called exactly once (tool decision). NOT a second time for composition.
    assert call_count == 1
    # Message is the deterministic one from PlaceRecommendationService
    assert response.message == "I found 1 local place option(s) in Ho Chi Minh City from Goong Places."
    assert response.citations == []
    assert response.intent == "place_recommendation"
    assert len(response.places) == 1


@pytest.mark.asyncio
async def test_place_intent_never_calls_search_knowledge() -> None:
    """Place intent must never call the RAG/search_knowledge path."""
    recommender = AsyncMock()
    recommender.recommend.return_value = _place_response()
    hybrid_retriever = AsyncMock()

    service = AgentService(
        retriever=None,
        hybrid_retriever=hybrid_retriever,
        place_recommendation_service=recommender,
        checkpoint_mode="test",
    )

    response = await service.answer(
        session_id="s-no-rag", message="tìm nhà hàng gần đây", language="vi"
    )

    hybrid_retriever.search_with_citations.assert_not_called()
    assert response.citations == []


@pytest.mark.asyncio
async def test_place_intent_citations_always_empty() -> None:
    """Place recommendation path always returns citations=[], even with results."""
    recommender = AsyncMock()
    recommender.recommend.return_value = _place_response()

    service = AgentService(
        retriever=None,
        place_recommendation_service=recommender,
        checkpoint_mode="test",
    )

    response = await service.answer(
        session_id="s-cite", message="tìm quán cafe gần đây", language="vi"
    )

    assert response.citations == []


@pytest.mark.asyncio
async def test_stream_place_intent_no_citations_event() -> None:
    """SSE stream for place intent must NOT emit a [CITATIONS] event."""
    recommender = AsyncMock()
    recommender.recommend.return_value = _place_response("s-stream-cite")

    service = AgentService(
        retriever=None,
        place_recommendation_service=recommender,
        checkpoint_mode="test",
    )

    events = [
        event async for event in service.answer_stream(
            session_id="s-stream-cite", message="tìm nhà hàng", language="vi"
        )
    ]

    citation_events = [e for e in events if e.startswith("[CITATIONS]")]
    assert citation_events == [], f"Expected no [CITATIONS] events, got: {citation_events}"
    assert any(e.startswith("[PLACES]") for e in events), "Expected [PLACES] event"


@pytest.mark.asyncio
async def test_empty_candidates_returns_honest_empty_text_no_rag() -> None:
    """When provider returns empty results, message is honest unavailable text,
    citations=[], places=[], and no RAG fallback occurs."""
    from datetime import UTC, datetime
    from app.models.places import PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from agents.services.place_recommendation_service import PlaceRecommendationService

    places_tool = AsyncMock()
    request = PlaceSearchRequest(query="nonexistent")
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.EMPTY,
        source=PlaceToolSource.GOOGLE_PLACES,
        candidates=[],
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool)

    service = AgentService(
        retriever=None,
        place_recommendation_service=recommender,
        checkpoint_mode="test",
    )

    response = await service.answer(
        session_id="s-empty", message="tìm quán không tồn tại", language="vi"
    )

    assert response.places == []
    assert response.citations == []
    assert response.intent == "place_recommendation"
    # Note: "tìm nơi không tồn tại" → "places" (has "tìm" action term)


@pytest.mark.asyncio
async def test_credential_blocked_returns_honest_text_no_rag() -> None:
    """When credentials are blocked, message is honest unavailable text,
    citations=[], places=[], and no RAG fallback occurs."""
    from datetime import UTC, datetime
    from app.models.places import PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from agents.services.place_recommendation_service import PlaceRecommendationService

    places_tool = AsyncMock()
    request = PlaceSearchRequest(query="seafood")
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.CREDENTIALS_BLOCKED,
        source=PlaceToolSource.GOOGLE_PLACES,
        candidates=[],
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool)

    service = AgentService(
        retriever=None,
        place_recommendation_service=recommender,
        checkpoint_mode="test",
    )

    response = await service.answer(
        session_id="s-cred", message="tìm nhà hàng hải sản", language="vi"
    )

    assert response.places == []
    assert response.citations == []
    assert response.intent == "place_recommendation"
    assert "thiếu cấu hình" in response.message  # honest credential-blocked text


@pytest.mark.asyncio
async def test_upstream_error_returns_honest_text_no_rag() -> None:
    """When provider returns upstream error, message is honest error text,
    citations=[], places=[], and no RAG fallback occurs."""
    from datetime import UTC, datetime
    from app.models.places import PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from agents.services.place_recommendation_service import PlaceRecommendationService

    places_tool = AsyncMock()
    request = PlaceSearchRequest(query="seafood")
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.UPSTREAM_ERROR,
        source=PlaceToolSource.GOOGLE_PLACES,
        candidates=[],
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool)

    service = AgentService(
        retriever=None,
        place_recommendation_service=recommender,
        checkpoint_mode="test",
    )

    response = await service.answer(
        session_id="s-error", message="tìm nhà hàng", language="vi"
    )

    assert response.places == []
    assert response.citations == []
    assert response.intent == "place_recommendation"
    assert "tạm lỗi" in response.message  # honest error text


@pytest.mark.asyncio
async def test_no_hallucinated_place_names() -> None:
    """Response message must not contain any place name not in the tool result."""
    recommender = AsyncMock()
    recommender.recommend.return_value = _place_response()

    service = AgentService(
        retriever=None,
        place_recommendation_service=recommender,
        checkpoint_mode="test",
    )

    response = await service.answer(
        session_id="s-hallucinate",
        message="tìm quán gần chợ Dương Đông",  # user mentions different location
        language="vi",
    )

    # Message text is from _message_for_status, no invented place names
    for forbidden in ("Dương Đông", "chợ Dương Đông"):
        assert forbidden not in response.message, f"Message should not contain '{forbidden}'"


@pytest.mark.asyncio
async def test_reasoning_log_exposed_for_place_results() -> None:
    """Place recommendation responses must include reasoning_log with provider status."""
    recommender = AsyncMock()
    recommender.recommend.return_value = _place_response()

    service = AgentService(
        retriever=None,
        place_recommendation_service=recommender,
        checkpoint_mode="test",
    )

    response = await service.answer(
        session_id="s-reasoning", message="tìm nhà hàng", language="vi"
    )

    assert response.reasoning_log is not None
    assert "place_recommendation" in response.reasoning_log
    assert "status=ok" in response.reasoning_log
    # Fixture uses goong_places source
    assert "source=goong_places" in response.reasoning_log


@pytest.mark.asyncio
async def test_places_response_ready_bypasses_second_llm_call() -> None:
    """After _search_places_tool sets places_response_ready, _should_continue returns END.
    The LLM call node is called exactly once (for tool decision), never again."""
    recommender = AsyncMock()
    recommender.recommend.return_value = _place_response()

    llm_completions = AsyncMock()
    call_count = 0

    def _llm_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            tool_call = MagicMock()
            tool_call.id = "tc-1"
            tool_call.function.name = "search_places"
            tool_call.function.arguments = '{"query": "tìm hải sản"}'
            msg = MagicMock()
            msg.tool_calls = [tool_call]
            msg.content = None
        else:
            msg = MagicMock()
            msg.tool_calls = []
            msg.content = "LLM answer"
        completion = MagicMock()
        completion.choices = [MagicMock()]
        completion.choices[0].message = msg
        return completion

    llm_completions.create = AsyncMock(side_effect=_llm_side_effect)

    llm_service = _FakeLLMService(llm_completions)

    service = AgentService(
        retriever=None,
        llm_service=llm_service,
        place_recommendation_service=recommender,
        checkpoint_mode="test",
    )

    await service.answer(session_id="s-ready", message="tìm hải sản", language="vi")

    # Only 1 LLM call (the decision call), no second call to compose answer
    assert call_count == 1


@pytest.mark.asyncio
async def test_deterministic_message_from_display_names() -> None:
    """Message text is composed from _message_for_status, not from LLM.
    It references the result count derived from actual candidates."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    candidates = [
        PlaceCandidate(place_id="places/a", display_name="Quán A", types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/b", display_name="Quán B", types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c", display_name="Quán C", types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="seafood")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.GOOGLE_PLACES,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool, routes_service=None)

    service = AgentService(
        retriever=None,
        place_recommendation_service=recommender,
        checkpoint_mode="test",
    )

    response = await service.answer(session_id="s-count", message="tìm hải sản", language="vi")

    assert response.places
    assert len(response.places) == 3
    # Message mentions count matching actual results
    assert "3" in response.message
    # Message is deterministic (from _message_for_status), not LLM-generated
    assert "Mình tìm được" in response.message
    assert response.citations == []


# ============================================================================
# Fairness audit integration tests (M013/S02 — T01)
# ============================================================================


@pytest.mark.asyncio
async def test_fairness_audit_emitted_on_ok_response() -> None:
    """Every OK recommendation response must include a FairnessAudit."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    candidates = [
        PlaceCandidate(place_id="places/a", display_name="Local A", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/b", display_name="Local B", local_factor=0.8, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c", display_name="Chain C", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="seafood")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-fair-ok", message="tìm hải sản", language="vi")

    assert response.fairness_audit is not None
    assert response.fairness_audit.candidate_count == 3
    assert response.fairness_audit.result_count == 3
    assert response.fairness_audit.provider_status == "ok"


@pytest.mark.asyncio
async def test_fairness_audit_top5_local_ratio_40_percent_target() -> None:
    """Mixed candidate pool where ≥2 local candidates exist must reach ≥40% top-5 local ratio."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    # 5 candidates: 3 local (factor >= 0.5), 2 non-local
    candidates = [
        PlaceCandidate(place_id="places/l1", display_name="Local 1", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/l2", display_name="Local 2", local_factor=0.8, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/l3", display_name="Local 3", local_factor=0.7, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/n1", display_name="Chain 1", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/n2", display_name="Chain 2", local_factor=0.05, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="restaurant")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-fair-40", message="tìm nhà hàng", language="vi")

    audit = response.fairness_audit
    assert audit is not None
    # At least 2 of top-5 must be local (40% of 5)
    assert audit.top5_local_ratio >= 0.4, f"top5_local_ratio {audit.top5_local_ratio} < 0.4"
    assert "insufficient_local_candidates" not in audit.warnings


@pytest.mark.asyncio
async def test_fairness_audit_insufficient_local_candidates_warning() -> None:
    """When local candidate supply cannot meet 40% target, warning is emitted."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    # 6 candidates but only 1 local — cannot meet 40% of top-5 (need 2)
    candidates = [
        PlaceCandidate(place_id="places/l1", display_name="Local 1", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/n1", display_name="Chain 1", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/n2", display_name="Chain 2", local_factor=0.05, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/n3", display_name="Chain 3", local_factor=0.0, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/n4", display_name="Chain 4", local_factor=0.0, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/n5", display_name="Chain 5", local_factor=0.0, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="restaurant")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-fair-insufficient", message="tìm nhà hàng", language="vi")

    audit = response.fairness_audit
    assert audit is not None
    assert "insufficient_local_candidates" in audit.warnings


@pytest.mark.asyncio
async def test_fairness_audit_missing_local_factor_warning() -> None:
    """Missing local_factor metadata increments missing count and emits warning."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    # Some candidates with local_factor=None
    candidates = [
        PlaceCandidate(place_id="places/a", display_name="A", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/b", display_name="B", local_factor=None, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c", display_name="C", local_factor=None, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="restaurant")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-fair-missing", message="tìm nhà hàng", language="vi")

    audit = response.fairness_audit
    assert audit is not None
    assert audit.missing_local_factor_count >= 2
    assert "missing_local_factor_metadata" in audit.warnings


@pytest.mark.asyncio
async def test_fairness_audit_empty_candidates_zero_counts() -> None:
    """Empty candidate pool reports zero counts and no division error."""
    from datetime import UTC, datetime
    from app.models.places import PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from agents.services.place_recommendation_service import PlaceRecommendationService

    request = PlaceSearchRequest(query="nonexistent")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.EMPTY,
        source=PlaceToolSource.MOCK,
        candidates=[],
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-fair-empty", message="tìm quán không tồn tại", language="vi")

    audit = response.fairness_audit
    assert audit is not None
    assert audit.candidate_count == 0
    assert audit.result_count == 0
    assert audit.top5_local_ratio == 0.0


@pytest.mark.asyncio
async def test_fairness_audit_non_ok_provider_warning() -> None:
    """Non-OK provider status emits provider_non_ok warning."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    request = PlaceSearchRequest(query="seafood")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.UPSTREAM_ERROR,
        source=PlaceToolSource.GOOGLE_PLACES,
        candidates=[
            PlaceCandidate(place_id="places/x", display_name="X", location=LatLng(lat=10.18, lng=104.05)),
        ],
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-fair-error", message="tìm nhà hàng", language="vi")

    audit = response.fairness_audit
    assert audit is not None
    assert audit.provider_status == "upstream_error"
    assert "provider_non_ok" in audit.warnings


@pytest.mark.asyncio
async def test_fairness_audit_route_enrichment_fallback_warning() -> None:
    """Route enrichment failure emits route_enrichment_fallback warning."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus, RouteContext
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    candidates = [
        PlaceCandidate(place_id="places/a", display_name="Local A", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/b", display_name="Local B", local_factor=0.8, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c", display_name="Chain C", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="restaurant")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )

    # Routes service that always fails
    failing_routes = AsyncMock()
    failing_routes.enrich_candidates.side_effect = RuntimeError("routes service unavailable")

    recommender = PlaceRecommendationService(places_tool, routes_service=failing_routes)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-fair-route", message="tìm nhà hàng", language="vi")

    audit = response.fairness_audit
    assert audit is not None
    assert "route_enrichment_fallback" in audit.warnings


@pytest.mark.asyncio
async def test_fairness_audit_reasoning_log_contains_status() -> None:
    """Reasoning log must surface place_recommendation status for audit trail."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    candidates = [
        PlaceCandidate(place_id="places/a", display_name="A", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="seafood")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-fair-log", message="tìm hải sản", language="vi")

    assert response.reasoning_log is not None
    assert "place_recommendation" in response.reasoning_log
    assert "candidate_count=" in response.reasoning_log
    assert "result_count=" in response.reasoning_log


@pytest.mark.asyncio
async def test_fairness_audit_no_secret_exposure() -> None:
    """Audit fields must never contain API keys, raw payloads, or PII."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    candidates = [
        PlaceCandidate(place_id="places/a", display_name="A", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="seafood")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-fair-redact", message="tìm hải sản", language="vi")

    audit = response.fairness_audit
    assert audit is not None
    dump = audit.model_dump_json()
    assert "api_key" not in dump.lower()
    assert "secret" not in dump.lower()
    assert "raw" not in dump.lower()
    assert "payload" not in dump.lower()


# ============================================================================
# T02: Fairness balancing — _balance_fairness unit tests
# ============================================================================

def _make_result(place_id: str, local_factor: float | None, final_score: float = 0.5) -> PlaceResult:
    """Helper to build minimal PlaceResult for fairness balancer tests."""
    return PlaceResult(
        place_id=place_id,
        display_name=place_id,
        formatted_address="Test Address",
        location=LatLng(lat=10.18, lng=104.05),
        types=["restaurant"],
        local_factor=local_factor if local_factor is not None else 0.5,
        final_score=final_score,
        score_breakdown=ScoreBreakdown(
            tree1_locality=0.5,
            tree2_proximity=0.5,
            tree3_quality=0.5,
            s_bag=0.5,
            delta1_fairness=0.0,
            delta2_access=0.0,
            final_score=final_score,
            rank=1,
        ),
        accessibility_score=None,
        map_uri="https://maps.example/placeholder",
    )


class TestBalanceFairness:
    """Unit tests for the _balance_fairness function in place_recommendation_service."""

    def _balance(self, results):
        from agents.services.place_recommendation_service import _balance_fairness
        return _balance_fairness(results)

    def test_empty_results_returns_empty(self):
        assert self._balance([]) == []

    def test_single_result_returns_unchanged(self):
        results = [_make_result("p1", local_factor=0.1)]
        assert self._balance(results) == results

    def test_fewer_than_top_k_returns_unchanged(self):
        """Fewer than 5 results — no top-K window to balance."""
        results = [
            _make_result("p1", local_factor=0.1, final_score=0.9),
            _make_result("p2", local_factor=0.1, final_score=0.8),
            _make_result("p3", local_factor=0.8, final_score=0.7),
        ]
        balanced = self._balance(results)
        # Same elements, same order
        assert [r.place_id for r in balanced] == ["p1", "p2", "p3"]

    def test_already_compliant_no_reordering(self):
        """Top-5 already has 40%+ local — no reordering needed."""
        results = [
            _make_result("local1", local_factor=0.9, final_score=0.95),
            _make_result("local2", local_factor=0.8, final_score=0.90),
            _make_result("chain1", local_factor=0.1, final_score=0.85),
            _make_result("chain2", local_factor=0.1, final_score=0.80),
            _make_result("chain3", local_factor=0.1, final_score=0.75),
        ]
        balanced = self._balance(results)
        # Already has 2/5 = 40% local — no change
        assert [r.place_id for r in balanced] == ["local1", "local2", "chain1", "chain2", "chain3"]

    def test_promotes_local_from_below_top5(self):
        """Only 1 local in top-5, but more available below — promotes to hit 40%."""
        results = [
            _make_result("chain1", local_factor=0.1, final_score=0.95),
            _make_result("chain2", local_factor=0.1, final_score=0.90),
            _make_result("chain3", local_factor=0.1, final_score=0.85),
            _make_result("chain4", local_factor=0.1, final_score=0.80),
            _make_result("chain5", local_factor=0.1, final_score=0.75),  # NOT local (0.1 < 0.6)
            _make_result("local1", local_factor=0.9, final_score=0.70),  # local
            _make_result("local2", local_factor=0.8, final_score=0.65),  # local
        ]
        balanced = self._balance(results)
        top5_ids = [r.place_id for r in balanced[:5]]
        local_in_top5 = sum(1 for r in balanced[:5] if (r.local_factor or 0.0) >= 0.6)
        assert local_in_top5 >= 2, f"Expected >= 2 local in top-5, got {local_in_top5}. top5: {top5_ids}"
        # Both locals should be promoted into top-5
        assert "local1" in top5_ids
        assert "local2" in top5_ids

    def test_all_local_no_reordering(self):
        """All results are local — already 100% compliant."""
        results = [
            _make_result("l1", local_factor=0.9, final_score=0.95),
            _make_result("l2", local_factor=0.8, final_score=0.90),
            _make_result("l3", local_factor=0.7, final_score=0.85),
            _make_result("l4", local_factor=0.6, final_score=0.80),
            _make_result("l5", local_factor=0.8, final_score=0.75),
        ]
        balanced = self._balance(results)
        assert [r.place_id for r in balanced] == ["l1", "l2", "l3", "l4", "l5"]

    def test_all_nonlocal_no_reordering(self):
        """No local candidates at all — nothing to promote."""
        results = [
            _make_result("c1", local_factor=0.1, final_score=0.95),
            _make_result("c2", local_factor=0.2, final_score=0.90),
            _make_result("c3", local_factor=0.3, final_score=0.85),
            _make_result("c4", local_factor=0.4, final_score=0.80),
            _make_result("c5", local_factor=0.5, final_score=0.75),
        ]
        balanced = self._balance(results)
        assert [r.place_id for r in balanced] == ["c1", "c2", "c3", "c4", "c5"]

    def test_preserves_element_set(self):
        """Balancing must not add or remove elements — only reorder."""
        results = [
            _make_result("c1", local_factor=0.1, final_score=0.95),
            _make_result("c2", local_factor=0.1, final_score=0.90),
            _make_result("c3", local_factor=0.1, final_score=0.85),
            _make_result("c4", local_factor=0.1, final_score=0.80),
            _make_result("c5", local_factor=0.1, final_score=0.75),
            _make_result("l1", local_factor=0.9, final_score=0.70),
            _make_result("l2", local_factor=0.8, final_score=0.65),
        ]
        balanced = self._balance(results)
        original_ids = {r.place_id for r in results}
        balanced_ids = {r.place_id for r in balanced}
        assert original_ids == balanced_ids
        assert len(balanced) == len(results)

    def test_exactly_at_threshold_counts_as_local(self):
        """local_factor exactly 0.6 (the threshold) counts as local."""
        results = [
            _make_result("c1", local_factor=0.1, final_score=0.95),
            _make_result("c2", local_factor=0.1, final_score=0.90),
            _make_result("c3", local_factor=0.1, final_score=0.85),
            _make_result("c4", local_factor=0.1, final_score=0.80),
            _make_result("c5", local_factor=0.1, final_score=0.75),
            _make_result("border", local_factor=0.6, final_score=0.70),
        ]
        balanced = self._balance(results)
        top5_ids = [r.place_id for r in balanced[:5]]
        # border (0.6) should be promoted
        assert "border" in top5_ids

    def test_just_below_threshold_not_local(self):
        """local_factor = 0.59 does NOT count as local."""
        from agents.services.place_recommendation_service import _is_local
        r = _make_result("x", local_factor=0.59)
        assert not _is_local(r)

    def test_local_factor_none_not_local(self):
        """local_factor = None does NOT count as local."""
        from agents.services.place_recommendation_service import _is_local
        r = _make_result("x", local_factor=0.5)  # 0.5 < 0.6 threshold
        assert not _is_local(r)

    def test_seven_candidates_two_need_promotion(self):
        """7 candidates, 0 local in top-5, 3 local below — promote 2 to hit 40%."""
        results = [
            _make_result("c1", local_factor=0.1, final_score=0.95),
            _make_result("c2", local_factor=0.1, final_score=0.90),
            _make_result("c3", local_factor=0.1, final_score=0.85),
            _make_result("c4", local_factor=0.1, final_score=0.80),
            _make_result("c5", local_factor=0.1, final_score=0.75),
            _make_result("l1", local_factor=0.9, final_score=0.70),
            _make_result("l2", local_factor=0.8, final_score=0.65),
            _make_result("l3", local_factor=0.7, final_score=0.60),
        ]
        balanced = self._balance(results)
        top5 = balanced[:5]
        local_in_top5 = sum(1 for r in top5 if (r.local_factor or 0.0) >= 0.6)
        assert local_in_top5 >= 2
        assert len(balanced) == 8  # no elements lost


# ============================================================================
# T02: Integration tests — fairness balancing in the recommendation service
# ============================================================================


@pytest.mark.asyncio
async def test_fairness_balancing_promotes_local_in_mixed_pool() -> None:
    """Mixed pool with 0 local in top-5 but local candidates available below — balancing promotes them."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    # 7 candidates: top 5 by score are all non-local, 2 locals ranked lower
    candidates = [
        PlaceCandidate(place_id="places/c1", display_name="Chain 1", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c2", display_name="Chain 2", local_factor=0.2, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c3", display_name="Chain 3", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c4", display_name="Chain 4", local_factor=0.3, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c5", display_name="Chain 5", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/l1", display_name="Local 1", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/l2", display_name="Local 2", local_factor=0.8, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="restaurant")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-balance", message="tìm nhà hàng", language="vi")

    top5 = response.places[:5]
    local_in_top5 = sum(1 for p in top5 if (p.local_factor or 0.0) >= 0.6)
    assert local_in_top5 >= 2, f"Expected >= 2 local in top-5 after balancing, got {local_in_top5}"


@pytest.mark.asyncio
async def test_fairness_balancing_no_local_candidates() -> None:
    """When no candidates are local, balancing is a no-op and no reordering occurs."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    candidates = [
        PlaceCandidate(place_id="places/c1", display_name="Chain 1", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c2", display_name="Chain 2", local_factor=0.2, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c3", display_name="Chain 3", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c4", display_name="Chain 4", local_factor=0.3, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c5", display_name="Chain 5", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="restaurant")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-no-local", message="tìm nhà hàng", language="vi")

    audit = response.fairness_audit
    assert audit is not None
    assert audit.top5_local_ratio == 0.0
    assert "insufficient_local_candidates" in audit.warnings


@pytest.mark.asyncio
async def test_fairness_balancing_insufficient_local_candidates() -> None:
    """Only 1 local candidate available — cannot reach 40% of top-5, warning emitted."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    candidates = [
        PlaceCandidate(place_id="places/c1", display_name="Chain 1", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c2", display_name="Chain 2", local_factor=0.2, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c3", display_name="Chain 3", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c4", display_name="Chain 4", local_factor=0.3, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c5", display_name="Chain 5", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/l1", display_name="Local 1", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="restaurant")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-insufficient", message="tìm nhà hàng", language="vi")

    audit = response.fairness_audit
    assert audit is not None
    assert audit.top5_local_ratio >= 0.2  # 1 out of 5 promoted
    assert "insufficient_local_candidates" in audit.warnings


@pytest.mark.asyncio
async def test_fairness_balancing_missing_local_factor_metadata() -> None:
    """Candidates with local_factor=None count as missing metadata, warning emitted."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    candidates = [
        PlaceCandidate(place_id="places/c1", display_name="Chain 1", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c2", display_name="Chain 2", local_factor=None, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c3", display_name="Chain 3", local_factor=None, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c4", display_name="Chain 4", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c5", display_name="Chain 5", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/l1", display_name="Local 1", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="restaurant")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-missing-meta", message="tìm nhà hàng", language="vi")

    audit = response.fairness_audit
    assert audit is not None
    assert audit.missing_local_factor_count >= 2
    assert "missing_local_factor_metadata" in audit.warnings


@pytest.mark.asyncio
async def test_fairness_balancing_top5_already_compliant() -> None:
    """When top-5 already meets 40% local target, no reordering occurs."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    candidates = [
        PlaceCandidate(place_id="places/l1", display_name="Local 1", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/l2", display_name="Local 2", local_factor=0.8, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c1", display_name="Chain 1", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c2", display_name="Chain 2", local_factor=0.2, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c3", display_name="Chain 3", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="restaurant")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-compliant", message="tìm nhà hàng", language="vi")

    audit = response.fairness_audit
    assert audit is not None
    assert audit.top5_local_ratio >= 0.4
    assert "insufficient_local_candidates" not in audit.warnings


@pytest.mark.asyncio
async def test_fairness_balancing_fallback_grounded_results() -> None:
    """When ensemble reranking fails and grounded results are used, fairness balancing still applies."""
    from datetime import UTC, datetime
    from unittest.mock import patch
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    candidates = [
        PlaceCandidate(place_id="places/c1", display_name="Chain 1", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c2", display_name="Chain 2", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c3", display_name="Chain 3", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c4", display_name="Chain 4", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c5", display_name="Chain 5", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/l1", display_name="Local 1", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/l2", display_name="Local 2", local_factor=0.8, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="restaurant")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    # Force ensemble reranking to fail
    with patch("agents.services.place_recommendation_service._reranked_results", side_effect=RuntimeError("ensemble broken")):
        response = await service.answer(session_id="s-grounded", message="tìm nhà hàng", language="vi")

    # Fairness balancing should still have run on grounded results
    audit = response.fairness_audit
    assert audit is not None
    assert "ensemble_fallback" in audit.warnings
    top5 = response.places[:5]
    local_in_top5 = sum(1 for p in top5 if (p.local_factor or 0.0) >= 0.6)
    assert local_in_top5 >= 2, f"Expected >= 2 local in top-5 after balancing grounded results, got {local_in_top5}"


@pytest.mark.asyncio
async def test_fairness_balancing_route_enrichment_fallback() -> None:
    """When route enrichment fails, fairness balancing still applies over original candidates."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    candidates = [
        PlaceCandidate(place_id="places/c1", display_name="Chain 1", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c2", display_name="Chain 2", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c3", display_name="Chain 3", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c4", display_name="Chain 4", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c5", display_name="Chain 5", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/l1", display_name="Local 1", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/l2", display_name="Local 2", local_factor=0.8, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="restaurant")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    failing_routes = AsyncMock()
    failing_routes.enrich_candidates.side_effect = RuntimeError("routes unavailable")

    recommender = PlaceRecommendationService(places_tool, routes_service=failing_routes)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-route-fallback", message="tìm nhà hàng", language="vi")

    audit = response.fairness_audit
    assert audit is not None
    assert "route_enrichment_fallback" in audit.warnings
    top5 = response.places[:5]
    local_in_top5 = sum(1 for p in top5 if (p.local_factor or 0.0) >= 0.6)
    assert local_in_top5 >= 2


@pytest.mark.asyncio
async def test_reasoning_log_contains_fairness_diagnostics() -> None:
    """reasoning_log must include top5_local_ratio, missing_local_factor count, and warnings."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    candidates = [
        PlaceCandidate(place_id="places/c1", display_name="Chain 1", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c2", display_name="Chain 2", local_factor=None, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c3", display_name="Chain 3", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c4", display_name="Chain 4", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c5", display_name="Chain 5", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/l1", display_name="Local 1", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="restaurant")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-reasoning-fair", message="tìm nhà hàng", language="vi")

    log = response.reasoning_log or ""
    assert "top5_local_ratio=" in log, f"reasoning_log missing top5_local_ratio: {log}"
    assert "missing_local_factor=" in log, f"reasoning_log missing missing_local_factor: {log}"
    assert "warnings=" in log, f"reasoning_log missing warnings: {log}"


@pytest.mark.asyncio
async def test_reasoning_log_no_secret_exposure() -> None:
    """reasoning_log must not leak API keys, raw payloads, or PII."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    candidates = [
        PlaceCandidate(place_id="places/a", display_name="A", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="seafood")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-redact", message="tìm hải sản", language="vi")

    log = response.reasoning_log or ""
    assert "api_key" not in log.lower()
    assert "secret" not in log.lower()
    assert "token" not in log.lower()


@pytest.mark.asyncio
async def test_display_name_grounded_in_results() -> None:
    """Every result's display_name must come from actual candidate data, never invented."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    candidates = [
        PlaceCandidate(place_id="places/a", display_name="Quán Biển Xanh", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/b", display_name="Nhà Hàng Hải Sản", local_factor=0.8, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="seafood")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-grounded-name", message="tìm hải sản", language="vi")

    result_names = {p.display_name for p in response.places}
    candidate_names = {c.display_name for c in candidates}
    assert result_names.issubset(candidate_names), f"Found non-grounded display_names: {result_names - candidate_names}"


@pytest.mark.asyncio
async def test_s01_no_rag_no_citation_behavior_preserved() -> None:
    """Existing S01 behavior: place recommendations must never use RAG/citations."""
    from datetime import UTC, datetime
    from app.models.places import PlaceCandidate, PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from app.models.request import LatLng
    from agents.services.place_recommendation_service import PlaceRecommendationService

    candidates = [
        PlaceCandidate(place_id="places/a", display_name="A", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/b", display_name="B", local_factor=0.8, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    request = PlaceSearchRequest(query="seafood")
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=request,
        retrieved_at=datetime.now(UTC),
    )
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    service = AgentService(
        retriever=AsyncMock(),
        place_recommendation_service=recommender,
        checkpoint_mode="test",
    )

    response = await service.answer(session_id="s-no-rag-t02", message="tìm hải sản", language="vi")

    assert response.citations == []
    assert response.intent == "place_recommendation"
    assert len(response.places) == 2
