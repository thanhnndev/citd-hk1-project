"""Tests for Goong Places service normalization and safe status mapping."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.models.places import PlaceDetailsRequest, PlaceNearbyRequest, PlaceSearchRequest, PlaceToolSource, PlaceToolStatus
from agents.tools.places_service import GoongPlacesService, normalize_place


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: object | None = None, json_error: Exception | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {"status": "OK", "results": []}
        self._json_error = json_error

    def json(self) -> object:
        if self._json_error:
            raise self._json_error
        return self._payload


class FakeClient:
    def __init__(self, responses: FakeResponse | Exception | list[FakeResponse | Exception]) -> None:
        self.responses = responses if isinstance(responses, list) else [responses]
        self.calls: list[tuple[str, object]] = []

    async def get(self, path: str, *, params: object) -> FakeResponse:
        self.calls.append((path, params))
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response


def settings(api_key: str = "test-goong-key") -> Settings:
    return Settings(OPENAI_API_KEY="openai-test", GOONG_API_KEY=api_key)


def goong_result(**overrides: object) -> dict[str, object]:
    place: dict[str, object] = {
        "place_id": "goong_ham_ninh",
        "name": "Ham Ninh Seafood Pier",
        "formatted_address": "Ham Ninh, Phu Quoc, Kien Giang",
        "geometry": {"location": {"lat": 10.1798, "lng": 104.0498}},
        "types": ["restaurant", "food"],
        "rating": 4.6,
        "user_ratings_total": 321,
        "price_level": 2,
        "opening_hours": {"open_now": True},
        "business_status": "OPERATIONAL",
        "formatted_phone_number": "091 234 5678",
        "international_phone_number": "+84 91 234 5678",
        "website": "https://example.test",
        "url": "https://goong.io/place/goong_ham_ninh",
        "distance_meters": 42,
    }
    place.update(overrides)
    return place


@pytest.mark.asyncio
async def test_missing_key_returns_credential_blocked_without_outbound_call():
    client = FakeClient(FakeResponse(payload={"status": "OK", "results": [goong_result()]}))
    service = GoongPlacesService(settings=settings(api_key=""), client=client)

    response = await service.text_search(PlaceSearchRequest(query="seafood"))

    assert response.status == PlaceToolStatus.CREDENTIALS_BLOCKED
    assert response.source == PlaceToolSource.GOONG_PLACES
    assert response.error and response.error.code == "missing_goong_api_key"
    assert response.metadata["error_code"] == "missing_goong_api_key"
    assert client.calls == []


@pytest.mark.asyncio
async def test_text_search_normalizes_goong_payload_and_rest_params():
    client = FakeClient(FakeResponse(payload={"status": "OK", "results": [goong_result()]}))
    service = GoongPlacesService(settings=settings(), client=client)

    response = await service.text_search(PlaceSearchRequest(query="seafood", max_result_count=3))

    assert response.status == PlaceToolStatus.OK
    candidate = response.candidates[0]
    assert candidate.place_id == "goong_ham_ninh"
    assert candidate.display_name == "Ham Ninh Seafood Pier"
    assert candidate.types == ["restaurant", "food"]
    assert candidate.formatted_address == "Ham Ninh, Phu Quoc, Kien Giang"
    assert candidate.location and candidate.location.lat == pytest.approx(10.1798)
    assert candidate.price_level == 2
    assert candidate.open_now is True
    assert candidate.business_status == "OPERATIONAL"
    assert candidate.national_phone_number == "091 234 5678"
    assert candidate.route_context and candidate.route_context.distance_meters == 42
    assert candidate.fairness_tags == ["accessibility_unknown"]
    path, params = client.calls[0]
    assert path == "/Place/TextSearch"
    assert params["input"] == "seafood"
    assert params["location"] == "10.1835208,104.0496843"
    assert params["radius"] == 5000
    assert params["limit"] == 3
    assert "test-goong-key" not in response.model_dump_json()


@pytest.mark.asyncio
async def test_text_search_hydrates_prediction_details_for_coordinates():
    prediction = {"place_id": "prediction_1", "description": "Ham Ninh Fishing Village"}
    detail = goong_result(place_id="prediction_1", name="Ham Ninh Fishing Village", distance_meters=None)
    client = FakeClient([
        FakeResponse(payload={"status": "OK", "predictions": [prediction]}),
        FakeResponse(payload={"status": "OK", "result": detail}),
    ])
    service = GoongPlacesService(settings=settings(), client=client)

    response = await service.text_search(PlaceSearchRequest(query="fishing", max_result_count=1))

    assert response.status == PlaceToolStatus.OK
    assert response.candidates[0].location is not None
    assert response.candidates[0].route_context and response.candidates[0].route_context.distance_meters is not None
    assert client.calls[1][0] == "/Place/Detail"
    assert client.calls[1][1]["place_id"] == "prediction_1"


@pytest.mark.asyncio
async def test_nearby_search_uses_center_radius_metadata_and_empty_results_envelope():
    client = FakeClient(FakeResponse(payload={"status": "ZERO_RESULTS", "predictions": []}))
    service = GoongPlacesService(settings=settings(), client=client)

    response = await service.nearby_search(PlaceNearbyRequest(included_type="restaurant"))

    assert response.status == PlaceToolStatus.EMPTY
    assert response.candidates == []
    assert response.error is None
    assert response.metadata["endpoint"] == "goong_autocomplete_nearby_approximation"
    assert response.metadata["radius_meters"] == 5000
    path, params = client.calls[0]
    assert path == "/Place/TextSearch"
    assert params["input"] == "restaurant"
    assert params["location"] == "10.1835208,104.0496843"
    assert params["radius"] == 5000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code,error_code,retryable",
    [(401, "auth_error", False), (403, "auth_error", False), (429, "quota_exceeded", True), (500, "upstream_error", True)],
)
async def test_http_failure_statuses_map_to_safe_errors(status_code: int, error_code: str, retryable: bool):
    service = GoongPlacesService(settings=settings(), client=FakeClient(FakeResponse(status_code=status_code)))

    response = await service.text_search(PlaceSearchRequest(query="coffee"))

    assert response.status == PlaceToolStatus.UPSTREAM_ERROR
    assert response.error and response.error.code == error_code
    assert response.error.retryable is retryable
    assert response.metadata["error_code"] == error_code
    assert response.candidates == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "upstream_status,error_code,retryable",
    [("REQUEST_DENIED", "auth_error", False), ("OVER_QUERY_LIMIT", "quota_exceeded", True), ("UNKNOWN_ERROR", "upstream_error", True)],
)
async def test_goong_status_failures_map_to_safe_errors(upstream_status: str, error_code: str, retryable: bool):
    service = GoongPlacesService(settings=settings(), client=FakeClient(FakeResponse(payload={"status": upstream_status, "error_message": "secret upstream body"})))

    response = await service.text_search(PlaceSearchRequest(query="coffee"))

    assert response.status == PlaceToolStatus.UPSTREAM_ERROR
    assert response.error and response.error.code == error_code
    assert response.error.retryable is retryable
    assert "secret upstream body" not in response.model_dump_json()


@pytest.mark.asyncio
async def test_timeout_maps_to_safe_retryable_error():
    service = GoongPlacesService(settings=settings(), client=FakeClient(httpx.TimeoutException("boom")))

    response = await service.text_search(PlaceSearchRequest(query="coffee"))

    assert response.status == PlaceToolStatus.UPSTREAM_ERROR
    assert response.error and response.error.code == "timeout"
    assert response.error.retryable is True


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"unexpected": []}, {"status": "OK", "results": {"bad": "shape"}}])
async def test_malformed_response_shape_maps_to_safe_error(payload: object):
    service = GoongPlacesService(settings=settings(), client=FakeClient(FakeResponse(payload=payload)))

    response = await service.text_search(PlaceSearchRequest(query="coffee"))

    assert response.status == PlaceToolStatus.UPSTREAM_ERROR
    assert response.error and response.error.code == "malformed_response"


@pytest.mark.asyncio
async def test_malformed_json_maps_to_safe_error():
    service = GoongPlacesService(settings=settings(), client=FakeClient(FakeResponse(json_error=ValueError("not json"))))

    response = await service.text_search(PlaceSearchRequest(query="coffee"))

    assert response.status == PlaceToolStatus.UPSTREAM_ERROR
    assert response.error and response.error.code == "malformed_response"


@pytest.mark.asyncio
async def test_details_normalizes_single_goong_detail_payload():
    client = FakeClient(FakeResponse(payload={"status": "OK", "result": goong_result(price_level="3")}))
    service = GoongPlacesService(settings=settings(), client=client)

    response = await service.details(PlaceDetailsRequest(place_id="places/goong_ham_ninh"))

    assert response.status == PlaceToolStatus.OK
    assert response.candidates[0].price_level == 3
    path, params = client.calls[0]
    assert path == "/Place/Detail"
    assert params["place_id"] == "goong_ham_ninh"


def test_normalize_place_supports_origin_distance_math_when_detail_missing_distance():
    candidate = normalize_place(
        goong_result(distance_meters=None, price_level=1),
        origin=PlaceSearchRequest(query="seafood").location_bias,
    )

    assert candidate is not None
    assert candidate.price_level == 1
    assert candidate.route_context and candidate.route_context.distance_meters is not None
