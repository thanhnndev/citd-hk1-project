"""Tests for normalized Goong Places tool contracts."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.places import (
    HAM_NINH_CENTER,
    PlaceCandidate,
    PlaceDetailsRequest,
    PlaceNearbyRequest,
    PlaceSearchRequest,
    PlaceToolError,
    PlaceToolResponse,
    PlaceToolSource,
    PlaceToolStatus,
)
from app.models.request import LatLng
from app.models.response import ChatResponse


def test_place_candidate_accepts_fairness_ready_fields():
    candidate = PlaceCandidate(
        place_id="places/ham-ninh-seafood",
        display_name="Quan hai san Ham Ninh",
        formatted_address="Ham Ninh, Phu Quoc, Kien Giang",
        location={"lat": 10.1835208, "lng": 104.0496843},
        primary_type="seafood_restaurant",
        rating=4.6,
        user_rating_count=321,
        price_level=2,
        accessibility_score=0.75,
        accessibility_warning="Call ahead to confirm step-free entrance.",
        local_factor=0.9,
        fairness_tags=["local_owned", "accessibility_unknown"],
        route_context={"origin": {"lat": 10.18, "lng": 104.05}, "travel_mode": "walk"},
        google_maps_uri="https://maps.google.com/?cid=abc",
    )

    assert candidate.place_id == "places/ham-ninh-seafood"
    assert candidate.location == LatLng(lat=10.1835208, lng=104.0496843)
    assert candidate.local_factor == 0.9
    assert candidate.fairness_tags == ["local_owned", "accessibility_unknown"]


def test_place_tool_response_echoes_request_and_safe_status_envelope():
    request = PlaceSearchRequest(query="seafood in Ham Ninh")
    retrieved_at = datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)

    response = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        request=request,
        retrieved_at=retrieved_at,
        candidates=[PlaceCandidate(place_id="places/1", display_name="Ham Ninh Pier")],
        metadata={"field_mask": "places.id,places.displayName"},
    )

    assert response.request == request
    assert response.retrieved_at == retrieved_at
    assert response.error is None
    assert "api_key" not in response.model_dump_json().lower()


def test_error_response_uses_sanitized_error_model_without_raw_payload():
    response = PlaceToolResponse(
        status=PlaceToolStatus.CREDENTIALS_BLOCKED,
        source=PlaceToolSource.GOONG_PLACES,
        request=PlaceNearbyRequest(included_type="restaurant"),
        retrieved_at=datetime.now(UTC),
        error=PlaceToolError(
            code="missing_goong_api_key",
            message="Goong Places credentials are not configured.",
            retryable=False,
        ),
    )

    serialized = response.model_dump()
    assert serialized["source"] == "goong_places"
    assert serialized["error"]["code"] == "missing_goong_api_key"
    assert "raw" not in serialized


def test_status_and_source_reject_unsupported_values():
    with pytest.raises(ValidationError):
        PlaceToolResponse(
            status="partial_success",
            source=PlaceToolSource.MOCK,
            request=PlaceSearchRequest(query="cafe"),
            retrieved_at=datetime.now(UTC),
        )

    with pytest.raises(ValidationError):
        PlaceToolResponse(
            status=PlaceToolStatus.OK,
            source="browser_google_maps",
            request=PlaceSearchRequest(query="cafe"),
            retrieved_at=datetime.now(UTC),
        )


def test_text_search_requires_non_empty_constrained_query():
    with pytest.raises(ValidationError):
        PlaceSearchRequest(query="")

    with pytest.raises(ValidationError):
        PlaceSearchRequest(query="x" * 161)


def test_invalid_lat_lng_rejected_for_requests_and_candidates():
    with pytest.raises(ValidationError):
        PlaceNearbyRequest(center={"lat": 91.0, "lng": 104.0}, included_type="restaurant")

    with pytest.raises(ValidationError):
        PlaceCandidate(place_id="places/1", display_name="Bad", location={"lat": 10.0, "lng": 181.0})


def test_candidate_requires_place_id_and_display_name():
    with pytest.raises(ValidationError):
        PlaceCandidate(display_name="Missing id")

    with pytest.raises(ValidationError):
        PlaceCandidate(place_id="places/1", display_name="")


def test_ham_ninh_defaults_are_server_side_request_defaults():
    request = PlaceSearchRequest(query="bun quay")

    assert request.location_bias == HAM_NINH_CENTER
    assert request.radius_meters == 5000


def test_chat_response_model_does_not_require_places_tool_metadata():
    response = ChatResponse(
        session_id="sess-1",
        message="Try these local options.",
        places=[],
        citations=[],
        latency_ms=12.5,
    )

    assert response.places == []
    assert response.fallback is False


def test_details_request_constrains_place_id():
    with pytest.raises(ValidationError):
        PlaceDetailsRequest(place_id="")
