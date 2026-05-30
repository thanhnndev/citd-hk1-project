"""Tests for Google Places (New) service normalization, typed contract, and safe status mapping."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.models.places import (
    GOOGLE_PLACES_FIELD_MASK,
    PlaceCandidate,
    PlaceDetailsRequest,
    PlaceNearbyRequest,
    PlaceSearchRequest,
    PlaceToolSource,
    PlaceToolStatus,
    ProviderStatus,
    SearchPlacesToolResult,
)
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
    return Settings(OPENAI_API_KEY="openai-test", GOOGLE_PLACES_API_KEY=api_key)


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


# ---------------------------------------------------------------------------
# Credential and auth tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_key_returns_credential_blocked_without_outbound_call():
    client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
    service = GooglePlacesService(settings=settings(api_key=""), client=client)

    response = await service.text_search(PlaceSearchRequest(query="seafood"))

    assert response.status == PlaceToolStatus.CREDENTIALS_BLOCKED
    assert response.source == PlaceToolSource.GOOGLE_PLACES
    assert response.reasoning_log
    assert any("credential" in entry.lower() for entry in response.reasoning_log)
    assert client.post_calls == []


@pytest.mark.asyncio
async def test_credential_blocked_includes_provider_status():
    service = GooglePlacesService(settings=settings(api_key=""), client=FakeClient(FakeResponse()))

    response = await service.text_search(PlaceSearchRequest(query="test"))

    assert isinstance(response.provider_status, ProviderStatus)
    assert response.retrieved_at is not None


# ---------------------------------------------------------------------------
# Normalized payload and field-mask tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_text_search_normalizes_google_payload_and_rest_params():
    client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
    service = GooglePlacesService(settings=settings(), client=client)

    response = await service.text_search(PlaceSearchRequest(query="seafood", max_result_count=3))

    assert response.status == PlaceToolStatus.OK
    assert response.source == PlaceToolSource.GOOGLE_PLACES
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


@pytest.mark.asyncio
async def test_text_search_sends_google_field_mask_header():
    client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
    service = GooglePlacesService(settings=settings(), client=client)

    await service.text_search(PlaceSearchRequest(query="cafe"))

    _, _, headers = client.post_calls[0]
    assert "X-Goog-FieldMask" in headers
    field_mask = headers["X-Goog-FieldMask"]
    # Verify all required fields are present
    for required in ["places.id", "places.displayName", "places.formattedAddress",
                      "places.location", "places.rating", "places.priceLevel",
                      "places.accessibilityOptions", "places.businessStatus"]:
        assert required in field_mask, f"Missing {required} in X-Goog-FieldMask header"
    # No secrets in field mask
    assert "key" not in field_mask.lower()
    assert "secret" not in field_mask.lower()


@pytest.mark.asyncio
async def test_text_search_api_key_in_header_not_in_result():
    client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
    service = GooglePlacesService(settings=settings(), client=client)

    response = await service.text_search(PlaceSearchRequest(query="seafood"))

    _, _, headers = client.post_calls[0]
    assert "test-google-key" in headers["X-Goog-Api-Key"]
    # Key must not appear in serialized result
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


# ---------------------------------------------------------------------------
# Nearby search tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nearby_search_uses_center_radius_and_empty_results_envelope():
    client = FakeClient(FakeResponse(payload={"places": []}))
    service = GooglePlacesService(settings=settings(), client=client)

    response = await service.nearby_search(PlaceNearbyRequest(included_type="restaurant"))

    assert response.status == PlaceToolStatus.EMPTY
    assert response.candidates == []
    assert response.source == PlaceToolSource.GOOGLE_PLACES
    assert response.audit.get("endpoint") == "google_nearby_search"
    assert len(client.post_calls) == 1
    path, body, headers = client.post_calls[0]
    assert path == "/v1/places:searchNearby"
    assert body["includedTypes"] == ["restaurant"]
    assert body["locationRestriction"]["circle"]["radius"] == 5000
    assert "X-Goog-FieldMask" in headers


# ---------------------------------------------------------------------------
# HTTP failure status mapping tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code,error_code,retryable",
    [(401, "auth_error", False), (403, "auth_error", False), (429, "quota_exceeded", True), (500, "upstream_error", True)],
)
async def test_http_failure_statuses_map_to_safe_errors(status_code: int, error_code: str, retryable: bool):
    service = GooglePlacesService(settings=settings(), client=FakeClient(FakeResponse(status_code=status_code)))

    response = await service.text_search(PlaceSearchRequest(query="coffee"))

    assert response.status == PlaceToolStatus.UPSTREAM_ERROR
    assert response.warnings or response.reasoning_log  # has diagnostics
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
    assert response.candidates == []


@pytest.mark.asyncio
async def test_timeout_maps_to_safe_retryable_error():
    service = GooglePlacesService(settings=settings(), client=FakeClient(httpx.TimeoutException("boom")))

    response = await service.text_search(PlaceSearchRequest(query="coffee"))

    assert response.status == PlaceToolStatus.UPSTREAM_ERROR
    assert response.candidates == []


@pytest.mark.asyncio
async def test_generic_exception_maps_to_safe_error():
    service = GooglePlacesService(settings=settings(), client=FakeClient(RuntimeError("network unavailable")))

    response = await service.text_search(PlaceSearchRequest(query="coffee"))

    assert response.status == PlaceToolStatus.UPSTREAM_ERROR
    assert response.candidates == []


# ---------------------------------------------------------------------------
# Malformed response tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"unexpected": []}, {"places": {"bad": "shape"}}])
async def test_malformed_response_shape_maps_to_safe_error(payload: object):
    service = GooglePlacesService(settings=settings(), client=FakeClient(FakeResponse(payload=payload)))

    response = await service.text_search(PlaceSearchRequest(query="coffee"))

    assert response.status == PlaceToolStatus.UPSTREAM_ERROR
    assert response.candidates == []


@pytest.mark.asyncio
async def test_malformed_json_maps_to_safe_error():
    service = GooglePlacesService(settings=settings(), client=FakeClient(FakeResponse(json_error=ValueError("not json"))))

    response = await service.text_search(PlaceSearchRequest(query="coffee"))

    assert response.status == PlaceToolStatus.UPSTREAM_ERROR
    assert response.candidates == []


# ---------------------------------------------------------------------------
# Details endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_details_normalizes_single_google_detail_payload():
    client = FakeClient(FakeResponse(payload=google_place(priceLevel="PRICE_LEVEL_EXPENSIVE")))
    service = GooglePlacesService(settings=settings(), client=client)

    response = await service.details(PlaceDetailsRequest(place_id="places/google_ham_ninh"))

    assert response.status == PlaceToolStatus.OK
    assert response.candidates[0].price_level == 3
    assert response.source == PlaceToolSource.GOOGLE_PLACES
    assert len(client.get_calls) == 1
    path, headers = client.get_calls[0]
    assert path == "/v1/places/google_ham_ninh"
    assert "X-Goog-Api-Key" in headers
    assert "X-Goog-FieldMask" in headers


@pytest.mark.asyncio
async def test_details_sends_field_mask_header():
    client = FakeClient(FakeResponse(payload=google_place()))
    service = GooglePlacesService(settings=settings(), client=client)

    await service.details(PlaceDetailsRequest(place_id="places/test"))

    _, headers = client.get_calls[0]
    field_mask = headers["X-Goog-FieldMask"]
    for required in ["places.id", "places.displayName", "places.location"]:
        assert required in field_mask


# ---------------------------------------------------------------------------
# Empty places and negative tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_provider_places_returns_empty_status():
    client = FakeClient(FakeResponse(payload={"places": []}))
    service = GooglePlacesService(settings=settings(), client=client)

    response = await service.text_search(PlaceSearchRequest(query="nonexistent place"))

    assert response.status == PlaceToolStatus.EMPTY
    assert response.candidates == []
    assert response.source == PlaceToolSource.GOOGLE_PLACES


@pytest.mark.asyncio
async def test_malformed_place_entries_skipped_silently():
    """Provider returns mix of valid and malformed entries; only valid ones normalize."""
    client = FakeClient(FakeResponse(payload={
        "places": [
            google_place(id="valid_place"),
            {"no_id_field": True},  # missing id → skipped
            "not_a_dict",  # not a dict → skipped
            None,  # null → skipped
        ]
    }))
    service = GooglePlacesService(settings=settings(), client=client)

    response = await service.text_search(PlaceSearchRequest(query="mixed"))

    assert response.status == PlaceToolStatus.OK
    assert len(response.candidates) == 1
    assert response.candidates[0].place_id == "valid_place"


@pytest.mark.asyncio
async def test_no_secrets_in_any_error_response():
    """All error paths must not leak API keys, tokens, or raw provider payloads."""
    service = GooglePlacesService(settings=settings(), client=FakeClient(FakeResponse(status_code=500)))

    response = await service.text_search(PlaceSearchRequest(query="test"))

    dump = response.model_dump_json()
    assert "test-google-key" not in dump
    assert "api_key" not in dump.lower() or "missing_google_api_key" in dump.lower()  # only safe code names
    assert "secret" not in dump.lower()


# ---------------------------------------------------------------------------
# Reasoning log and audit field tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reasoning_log_populated_for_ok_response():
    client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
    service = GooglePlacesService(settings=settings(), client=client)

    response = await service.text_search(PlaceSearchRequest(query="test"))

    assert response.reasoning_log
    assert any("normalized" in entry.lower() for entry in response.reasoning_log)


@pytest.mark.asyncio
async def test_reasoning_log_populated_for_credential_blocked():
    service = GooglePlacesService(settings=settings(api_key=""), client=FakeClient(FakeResponse()))

    response = await service.text_search(PlaceSearchRequest(query="test"))

    assert response.reasoning_log
    assert any("credential" in entry.lower() for entry in response.reasoning_log)


@pytest.mark.asyncio
async def test_audit_includes_endpoint_and_field_mask():
    client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
    service = GooglePlacesService(settings=settings(), client=client)

    response = await service.text_search(PlaceSearchRequest(query="test"))

    assert "endpoint" in response.audit
    assert "field_mask" in response.audit
    assert response.audit["field_mask"] == GOOGLE_PLACES_FIELD_MASK


# ---------------------------------------------------------------------------
# normalize_place helper tests
# ---------------------------------------------------------------------------

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


def test_normalize_place_returns_none_for_missing_id():
    assert normalize_place({"displayName": {"text": "No ID"}}) is None
