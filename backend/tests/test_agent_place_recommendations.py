"""AgentService place-intent routing tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.models.response import ChatResponse, PlaceResult, ScoreBreakdown
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
        google_maps_uri="https://maps.example/ham-ninh-seafood",
    )


def _place_response(session_id: str = "s-place") -> ChatResponse:
    return ChatResponse(
        session_id=session_id,
        message="I found 1 Ham Ninh place option(s) from Google Places.",
        citations=[],
        places=[_place()],
        reasoning_log="place_recommendation status=ok source=google_places candidate_count=1 result_count=1",
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
    llm.answer.assert_awaited_once()
    assert response.intent == "cultural_query"
    assert response.places == []


@pytest.mark.asyncio
async def test_missing_recommendation_dependency_fails_honestly_without_llm() -> None:
    llm = AsyncMock()
    service = AgentService(retriever=None, llm_service=llm, checkpoint_mode="test")

    response = await service.answer(session_id="s-missing", message="Recommend a place in Ham Ninh", language="en")

    llm.answer.assert_not_called()
    assert response.fallback is True
    assert response.places == []
    assert response.intent == "place_recommendation"
    assert "not configured" in response.message
    assert response.reasoning_log is not None


@pytest.mark.asyncio
async def test_recommendation_exception_is_sanitized() -> None:
    recommender = AsyncMock()
    recommender.recommend.side_effect = RuntimeError("secret provider payload")
    service = AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-error", message="Gợi ý dịch vụ ở Hàm Ninh", language="vi")

    assert response.fallback is True
    assert response.places == []
    assert "secret provider payload" not in response.message
    assert response.reasoning_log == "place_recommendation status=upstream_error source=none candidate_count=0 result_count=0"


@pytest.mark.asyncio
async def test_stream_place_intent_uses_deterministic_text_and_no_structured_places_marker() -> None:
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
    assert "I found 1 Ham Ninh place option(s) from Google Places." in events
    assert "[CITATIONS] []" in events
    assert "[DONE]" in events
    assert not any(event.startswith("[PLACES]") for event in events)

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
        google_maps_uri="https://maps.example/pin-ready",
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
