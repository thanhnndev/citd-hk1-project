"""Tests for Google Places (New) service normalization and safe status mapping."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.models.places import PlaceDetailsRequest, PlaceNearbyRequest, PlaceSearchRequest, PlaceToolSource, PlaceToolStatus
from agents.tools.places_service import GooglePlacesService, normalize_place


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: object | None = None, json_error: Exception | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {"places": []}
        self._json_error = json_error

    def json(self) -> object:
        if self._json_error:
            raise self._json_error
        return self._payload


class FakeClient:
    def __init__(self, responses: FakeResponse | Exception | list[FakeResponse | Exception]) -> None:
        self.responses = responses if isinstance(responses, list) else [responses]
        self.post_calls: list[tuple[str, dict, dict]] = []
        self.get_calls: list[tuple[str, dict]] = []

    async def post(self, path: str, *, json: dict, headers: dict) -> FakeResponse:
        self.post_calls.append((path, json, headers))
        response = self.responses[min(len(self.post_calls) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response

    async def get(self, path: str, *, headers: dict) -> FakeResponse:
        self.get_calls.append((path, headers))
        response = self.responses[min(len(self.get_calls) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response


def settings(api_key: str = "test-google-key") -> Settings:
    return Settings(OPENAI_API_KEY="openai-test", GOONG_API_KEY=api_key)


def google_place(**overrides: object) -> dict[str, object]:
    place: dict[str, object] = {
        "id": "google_ham_ninh",
        "displayName": {"text": "Ham Ninh Seafood Pier"},
        "formattedAddress": "Ham Ninh, Phu Quoc, Kien Giang",
        "location": {"lat": 10.1798, "lng": 104.0498},
        "types": ["restaurant", "food"],
        "primaryType": "restaurant",
        "rating": 4.6,
        "userRatingCount": 321,
        "priceLevel": "PRICE_LEVEL_MODERATE",
        "currentOpeningHours": {"openNow": True},
        "businessStatus": "OPERATIONAL",
        "nationalPhoneNumber": "091 234 5678",
        "internationalPhoneNumber": "+84 91 234 5678",
        "googleMapsUri": "https://maps.google.com/?q=place_id:google_ham_ninh",
        "websiteUri": "https://example.test",
    }
    place.update(overrides)
    return place


@pytest.mark.asyncio
async def test_missing_key_returns_credential_blocked_without_outbound_call():
    client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
    service = GooglePlacesService(settings=settings(api_key=""), client=client)

    response = await service.text_search(PlaceSearchRequest(query="seafood"))

    assert response.status == PlaceToolStatus.CREDENTIALS_BLOCKED
    assert response.source == PlaceToolSource.GOONG_PLACES
    assert response.error and response.error.code == "missing_google_api_key"
    assert response.metadata["error_code"] == "missing_google_api_key"
    assert client.post_calls == []


@pytest.mark.asyncio
async def test_text_search_normalizes_google_payload_and_rest_params():
    client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
    service = GooglePlacesService(settings=settings(), client=client)

    response = await service.text_search(PlaceSearchRequest(query="seafood", max_result_count=3))

    assert response.status == PlaceToolStatus.OK
    candidate = response.candidates[0]
    assert candidate.place_id == "google_ham_ninh"
    assert candidate.display_name == "Ham Ninh Seafood Pier"
    assert candidate.types == ["restaurant", "food"]
    assert candidate.formatted_address == "Ham Ninh, Phu Quoc, Kien Giang"
    assert candidate.location and candidate.location.lat == pytest.approx(10.1798)
    assert candidate.price_level == 2
    assert candidate.open_now is True
    assert candidate.business_status == "OPERATIONAL"
    assert candidate.national_phone_number == "091 234 5678"
    assert candidate.route_context and candidate.route_context.distance_meters is not None
    assert candidate.fairness_tags == ["accessibility_unknown"]
    assert len(client.post_calls) == 1
    path, body, headers = client.post_calls[0]
    assert path == "/v1/places:searchText"
    assert body["textQuery"] == "seafood"
    assert body["maxResultCount"] == 3
    assert "X-Goog-Api-Key" in headers
    assert "X-Goog-FieldMask" in headers
    assert "test-google-key" not in response.model_dump_json()


@pytest.mark.asyncio
async def test_text_search_with_location_bias():
    client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
    service = GooglePlacesService(settings=settings(), client=client)

    await service.text_search(PlaceSearchRequest(query="seafood", max_result_count=3))

    body = client.post_calls[0][1]
    assert "locationBias" in body
    assert body["locationBias"]["circle"]["center"]["latitude"] == pytest.approx(10.1835208)
    assert body["locationBias"]["circle"]["center"]["longitude"] == pytest.approx(104.0496843)
    assert body["locationBias"]["circle"]["radius"] == 5000


@pytest.mark.asyncio
async def test_nearby_search_uses_center_radius_and_empty_results_envelope():
    client = FakeClient(FakeResponse(payload={"places": []}))
    service = GooglePlacesService(settings=settings(), client=client)

    response = await service.nearby_search(PlaceNearbyRequest(included_type="restaurant"))

    assert response.status == PlaceToolStatus.EMPTY
    assert response.candidates == []
    assert response.error is None
    assert response.metadata["endpoint"] == "google_nearby_search"
    assert response.metadata["radius_meters"] == 5000
    assert len(client.post_calls) == 1
    path, body, headers = client.post_calls[0]
    assert path == "/v1/places:searchNearby"
    assert body["includedTypes"] == ["restaurant"]
    assert body["locationRestriction"]["circle"]["radius"] == 5000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code,error_code,retryable",
    [(401, "auth_error", False), (403, "auth_error", False), (429, "quota_exceeded", True), (500, "upstream_error", True)],
)
async def test_http_failure_statuses_map_to_safe_errors(status_code: int, error_code: str, retryable: bool):
    service = GooglePlacesService(settings=settings(), client=FakeClient(FakeResponse(status_code=status_code)))

    response = await service.text_search(PlaceSearchRequest(query="coffee"))

    assert response.status == PlaceToolStatus.UPSTREAM_ERROR
    assert response.error and response.error.code == error_code
    assert response.error.retryable is retryable
    assert response.metadata["error_code"] == error_code
    assert response.candidates == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_status,error_code,retryable",
    [("REQUEST_DENIED", "auth_error", False), ("PERMISSION_DENIED", "auth_error", False), ("RESOURCE_EXHAUSTED", "quota_exceeded", True)],
)
async def test_google_error_envelope_maps_to_safe_errors(error_status: str, error_code: str, retryable: bool):
    service = GooglePlacesService(settings=settings(), client=FakeClient(FakeResponse(payload={"error": {"status": error_status, "message": "some error"}})))

    response = await service.text_search(PlaceSearchRequest(query="coffee"))

    assert response.status == PlaceToolStatus.UPSTREAM_ERROR
    assert response.error and response.error.code == error_code
    assert response.error.retryable is retryable


@pytest.mark.asyncio
async def test_timeout_maps_to_safe_retryable_error():
    service = GooglePlacesService(settings=settings(), client=FakeClient(httpx.TimeoutException("boom")))

    response = await service.text_search(PlaceSearchRequest(query="coffee"))

    assert response.status == PlaceToolStatus.UPSTREAM_ERROR
    assert response.error and response.error.code == "timeout"
    assert response.error.retryable is True


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"unexpected": []}, {"places": {"bad": "shape"}}])
async def test_malformed_response_shape_maps_to_safe_error(payload: object):
    service = GooglePlacesService(settings=settings(), client=FakeClient(FakeResponse(payload=payload)))

    response = await service.text_search(PlaceSearchRequest(query="coffee"))

    assert response.status == PlaceToolStatus.UPSTREAM_ERROR
    assert response.error and response.error.code == "malformed_response"


@pytest.mark.asyncio
async def test_malformed_json_maps_to_safe_error():
    service = GooglePlacesService(settings=settings(), client=FakeClient(FakeResponse(json_error=ValueError("not json"))))

    response = await service.text_search(PlaceSearchRequest(query="coffee"))

    assert response.status == PlaceToolStatus.UPSTREAM_ERROR
    assert response.error and response.error.code == "malformed_response"


@pytest.mark.asyncio
async def test_details_normalizes_single_google_detail_payload():
    client = FakeClient(FakeResponse(payload=google_place(priceLevel="PRICE_LEVEL_EXPENSIVE")))
    service = GooglePlacesService(settings=settings(), client=client)

    response = await service.details(PlaceDetailsRequest(place_id="places/google_ham_ninh"))

    assert response.status == PlaceToolStatus.OK
    assert response.candidates[0].price_level == 3
    assert len(client.get_calls) == 1
    path, headers = client.get_calls[0]
    assert path == "/v1/places/google_ham_ninh"
    assert "X-Goog-Api-Key" in headers
    assert "X-Goog-FieldMask" in headers


def test_normalize_place_supports_origin_distance_math():
    candidate = normalize_place(
        google_place(priceLevel="PRICE_LEVEL_INEXPENSIVE"),
        origin=PlaceSearchRequest(query="seafood").location_bias,
    )

    assert candidate is not None
    assert candidate.price_level == 1
    assert candidate.route_context and candidate.route_context.distance_meters is not None


def test_normalize_place_google_price_level_enum():
    from agents.tools.places_service import _price_level_google

    assert _price_level_google("PRICE_LEVEL_FREE") == 0
    assert _price_level_google("PRICE_LEVEL_INEXPENSIVE") == 1
    assert _price_level_google("PRICE_LEVEL_MODERATE") == 2
    assert _price_level_google("PRICE_LEVEL_EXPENSIVE") == 3
    assert _price_level_google("PRICE_LEVEL_VERY_EXPENSIVE") == 4
    assert _price_level_google(2) == 2
    assert _price_level_google(None) is None
    assert _price_level_google("UNKNOWN") is None
