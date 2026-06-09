"""Accessibility truthfulness tests for place recommendations."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agents.services.place_recommendation_service import PlaceRecommendationService
from app.models.places import (
    PlaceCandidate,
    PlaceSearchRequest,
    PlaceToolResponse,
    PlaceToolSource,
    PlaceToolStatus,
)
from app.models.request import LatLng


class FakePlacesTool:
    def __init__(self, candidates: list[PlaceCandidate]) -> None:
        self.candidates = candidates
        self.last_request: PlaceSearchRequest | None = None

    async def text_search(self, request: PlaceSearchRequest) -> PlaceToolResponse:
        self.last_request = request
        return PlaceToolResponse(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.MOCK,
            candidates=self.candidates,
            request=request,
            retrieved_at=datetime.now(UTC),
        )


class PassthroughRoutes:
    async def enrich_candidates(
        self,
        candidates: list[PlaceCandidate],
        origin: LatLng,
    ) -> list[PlaceCandidate]:
        return candidates


def _restaurant(
    name: str,
    entrance: bool | None,
    *,
    place_id: str,
) -> PlaceCandidate:
    accessibility_options = {}
    if entrance is not None:
        accessibility_options["wheelchairAccessibleEntrance"] = entrance
    return PlaceCandidate(
        place_id=place_id,
        display_name=name,
        primary_type="restaurant",
        types=["restaurant"],
        formatted_address="Ham Ninh, Phu Quoc",
        location=LatLng(lat=10.18, lng=104.05),
        rating=4.2,
        user_rating_count=120,
        business_status="OPERATIONAL",
        accessibility_options=accessibility_options,
        geo_locality=1.0,
    )


@pytest.mark.asyncio
async def test_accessibility_request_filters_out_no_wheelchair_entrance() -> None:
    service = PlaceRecommendationService(
        places_tool=FakePlacesTool([
            _restaurant("Ngon Restaurant", False, place_id="no-access"),
        ]),
        routes_service=PassthroughRoutes(),
    )

    response = await service.recommend(
        query="nhà hàng nào hỗ trợ xe lăn?",
        language="vi",
        session_id="accessibility-false",
        accessibility=True,
    )

    assert response.places == []
    assert "không gắn nhãn hỗ trợ xe lăn" in response.message
    assert response.fairness_audit is not None
    assert response.fairness_audit.result_count == 0


@pytest.mark.asyncio
async def test_accessibility_request_keeps_only_verified_wheelchair_entrance() -> None:
    service = PlaceRecommendationService(
        places_tool=FakePlacesTool([
            _restaurant("Ngon Restaurant", False, place_id="no-access"),
            _restaurant("Verified Local Restaurant", True, place_id="verified-access"),
        ]),
        routes_service=PassthroughRoutes(),
    )

    response = await service.recommend(
        query="wheelchair accessible restaurants",
        language="en",
        session_id="accessibility-verified",
        accessibility=True,
    )

    assert [place.display_name for place in response.places] == ["Verified Local Restaurant"]
    verified = response.places[0]
    assert verified.accessibility_score == 1.0
    assert "provider metadata verifies" in verified.explanation.accessibility_note
    assert "accessibility_preference_matched" in verified.explanation.matched_preferences


@pytest.mark.asyncio
async def test_cafe_request_sets_strict_type_and_rejects_restaurants() -> None:
    restaurant = _restaurant("Cơm Niêu", True, place_id="restaurant")
    restaurant.display_name = "Cơm Niêu"
    restaurant.types = ["restaurant"]
    restaurant.primary_type = "restaurant"
    cafe = _restaurant("Cafe Hàm Ninh", True, place_id="cafe")
    cafe.display_name = "Cafe Hàm Ninh"
    cafe.types = ["cafe", "coffee_shop"]
    cafe.primary_type = "cafe"
    tool = FakePlacesTool([restaurant, cafe])
    service = PlaceRecommendationService(places_tool=tool, routes_service=PassthroughRoutes())

    response = await service.recommend(
        query="tìm quán cf gần tôi mà có lối đi cho xe lăn",
        language="vi",
        session_id="strict-cafe",
        accessibility=True,
        user_location={"lat": 10.18, "lng": 104.05},
    )

    assert tool.last_request is not None
    assert tool.last_request.included_type == "cafe"
    assert tool.last_request.strict_type_filtering is True
    assert [place.display_name for place in response.places] == ["Cafe Hàm Ninh"]
