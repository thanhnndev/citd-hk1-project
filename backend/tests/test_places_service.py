"""Tests for Google Places service normalization and safe status mapping."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.models.places import PlaceDetailsRequest, PlaceNearbyRequest, PlaceSearchRequest, PlaceToolStatus
from app.services.places_service import GooglePlacesService, normalize_place


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
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, str, object, object]] = []

    async def post(self, path: str, *, json: object, headers: object) -> FakeResponse:
        self.calls.append(("post", path, json, headers))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def get(self, path: str, *, headers: object, params: object | None = None) -> FakeResponse:
        self.calls.append(("get", path, params, headers))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def settings(api_key: str = "test-key") -> Settings:
    return Settings(OPENAI_API_KEY="openai-test", GOOGLE_PLACES_API_KEY=api_key)


def google_place(**overrides: object) -> dict[str, object]:
    place: dict[str, object] = {
        "id": "ChIJhamninh",
        "name": "places/ChIJhamninh",
        "displayName": {"text": "Ham Ninh Seafood Pier", "languageCode": "en"},
        "types": ["seafood_restaurant", "restaurant"],
        "primaryType": "seafood_restaurant",
        "formattedAddress": "Ham Ninh, Phu Quoc, Kien Giang",
        "shortFormattedAddress": "Ham Ninh, Phu Quoc",
        "location": {"latitude": 10.1798, "longitude": 104.0498},
        "rating": 4.6,
        "userRatingCount": 321,
        "priceLevel": "PRICE_LEVEL_MODERATE",
        "currentOpeningHours": {"openNow": True},
        "businessStatus": "OPERATIONAL",
        "accessibilityOptions": {"wheelchairAccessibleEntrance": True, "wheelchairAccessibleParking": False},
        "nationalPhoneNumber": "091 234 5678",
        "internationalPhoneNumber": "+84 91 234 5678",
        "websiteUri": "https://example.test",
        "googleMapsUri": "https://maps.google.com/?cid=1",
        "distanceMeters": 42,
    }
    place.update(overrides)
    return place


@pytest.mark.asyncio
async def test_missing_key_returns_credential_blocked_without_outbound_call():
    client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
    service = GooglePlacesService(settings=settings(api_key=""), client=client)

    response = await service.text_search(PlaceSearchRequest(query="seafood"))

    assert response.status == PlaceToolStatus.CREDENTIALS_BLOCKED
    assert response.error and response.error.code == "missing_google_places_api_key"
    assert client.calls == []


@pytest.mark.asyncio
async def test_text_search_normalizes_google_places_payload_and_headers():
    client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
    service = GooglePlacesService(settings=settings(), client=client)

    response = await service.text_search(PlaceSearchRequest(query="seafood", max_result_count=3))

    assert response.status == PlaceToolStatus.OK
    candidate = response.candidates[0]
    assert candidate.place_id == "ChIJhamninh"
    assert candidate.resource_name == "places/ChIJhamninh"
    assert candidate.display_name == "Ham Ninh Seafood Pier"
    assert candidate.types == ["seafood_restaurant", "restaurant"]
    assert candidate.short_formatted_address == "Ham Ninh, Phu Quoc"
    assert candidate.location and candidate.location.lat == pytest.approx(10.1798)
    assert candidate.price_level == 2
    assert candidate.open_now is True
    assert candidate.business_status == "OPERATIONAL"
    assert candidate.accessibility_options["wheelchairAccessibleEntrance"] is True
    assert candidate.national_phone_number == "091 234 5678"
    assert candidate.route_context and candidate.route_context.distance_meters == 42
    method, path, body, headers = client.calls[0]
    assert method == "post"
    assert path == "/places:searchText"
    assert body["textQuery"] == "seafood"
    assert "places.displayName" in headers["X-Goog-FieldMask"]
    assert "places.distanceMeters" not in headers["X-Goog-FieldMask"]
    assert "test-key" not in response.model_dump_json()


@pytest.mark.asyncio
async def test_nearby_search_empty_results_maps_to_zero_results_envelope():
    service = GooglePlacesService(settings=settings(), client=FakeClient(FakeResponse(payload={"places": []})))

    response = await service.nearby_search(PlaceNearbyRequest(included_type="restaurant"))

    assert response.status == PlaceToolStatus.EMPTY
    assert response.candidates == []
    assert response.error is None


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
    assert response.candidates == []


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
async def test_details_normalizes_single_place_payload():
    service = GooglePlacesService(settings=settings(), client=FakeClient(FakeResponse(payload=google_place(priceLevel="3"))))

    response = await service.details(PlaceDetailsRequest(place_id="places/ChIJhamninh"))

    assert response.status == PlaceToolStatus.OK
    assert response.candidates[0].price_level == 3
    assert client_call_path(service) == "/places/ChIJhamninh"


def test_normalize_place_supports_numeric_price_and_origin_distance_math():
    candidate = normalize_place(
        google_place(distanceMeters=None, priceLevel=1),
        origin=PlaceSearchRequest(query="seafood").location_bias,
    )

    assert candidate is not None
    assert candidate.price_level == 1
    assert candidate.route_context and candidate.route_context.distance_meters is not None


def client_call_path(service: GooglePlacesService) -> str:
    return service._client.calls[0][1]
