"""M014/S02: Google Places API New primary contract tests.

Defines the Google Places API New request/normalization envelope, the Goong
fallback path, and redacted diagnostics — before changing runtime wiring.

Contract surface:
- Text Search uses POST /v1/places:searchText with X-Goog-Api-Key and X-Goog-FieldMask.
- Field mask covers every rich field consumed by normalize_place() for S03/S04.
- Normalized PlaceCandidate includes coordinates, rating count, open-now,
  business status, phone, website, map URI, primary type, accessibility options.
- Missing Google credentials → credentials_blocked with honest diagnostics.
- Google auth/quota/timeout/malformed/5xx → honest upstream_error + cache fallback.
- No API keys, raw provider payloads, or phone numbers in serialized responses.
- Goong fallback is reported as fallback, not as Google success.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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
    SearchPlacesToolResult,
)
from app.models.request import LatLng
from agents.tools.places_service import (
    CircuitState,
    GooglePlacesService,
    HttpxPlacesClient,
    normalize_place,
    TEXT_SEARCH_PATH,
    NEARBY_SEARCH_PATH,
    DETAILS_PATH,
    PLACES_BASE_URL,
    _DEFAULT_FIELD_MASK,
)


# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------

def _settings(*, google_key: str = "test-google-key-abc123") -> Settings:
    return Settings(
        OPENAI_API_KEY="openai-test",
        GOOGLE_PLACES_API_KEY=google_key,
    )


def _no_key_settings() -> Settings:
    return Settings(
        OPENAI_API_KEY="openai-test",
        GOOGLE_PLACES_API_KEY="",
    )


def _fake_response(
    status_code: int = 200,
    payload: dict | None = None,
    json_error: Exception | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.side_effect = json_error or (lambda: payload if payload is not None else {"places": []})
    return resp


class FakeHttpClient:
    """Minimal mock HTTP client that records calls and returns controlled responses."""

    def __init__(self, responses: list[Any] | None = None) -> None:
        self._responses = responses or []
        self._call_index = 0
        self.post_calls: list[tuple[str, dict, dict]] = []
        self.get_calls: list[tuple[str, dict]] = []

    async def post(self, path: str, *, json: dict, headers: dict) -> Any:
        self.post_calls.append((path, dict(json), dict(headers)))
        resp = self._responses[min(self._call_index, len(self._responses) - 1)]
        self._call_index += 1
        if isinstance(resp, Exception):
            raise resp
        return resp

    async def get(self, path: str, *, headers: dict) -> Any:
        self.get_calls.append((path, dict(headers)))
        resp = self._responses[min(self._call_index, len(self._responses) - 1)]
        self._call_index += 1
        if isinstance(resp, Exception):
            raise resp
        return resp


def _google_place(**overrides: Any) -> dict[str, Any]:
    """Build a realistic Google Places API New place object."""
    place: dict[str, Any] = {
        "id": "ChIJgoogle_test_place_id",
        "displayName": {"text": "Hải Sản Hàm Ninh"},
        "formattedAddress": "Hàm Ninh, Phú Quốc, Kiên Giang, Vietnam",
        "shortFormattedAddress": "Hàm Ninh, Phú Quốc",
        "location": {"lat": 10.1798, "lng": 104.0498},
        "types": ["restaurant", "seafood_restaurant", "food", "point_of_interest"],
        "primaryType": "seafood_restaurant",
        "rating": 4.6,
        "userRatingCount": 321,
        "priceLevel": "PRICE_LEVEL_MODERATE",
        "currentOpeningHours": {"openNow": True},
        "businessStatus": "OPERATIONAL",
        "accessibilityOptions": {
            "wheelchairAccessibleParking": True,
            "wheelchairAccessibleEntrance": True,
        },
        "nationalPhoneNumber": "0297 3846 123",
        "internationalPhoneNumber": "+84 297 3846 123",
        "googleMapsUri": "https://maps.google.com/?q=place_id:ChIJgoogle_test_place_id",
        "websiteUri": "https://haisanhamninh.example.com",
    }
    place.update(overrides)
    return place


def _make_request(query: str = "seafood", **kwargs: Any) -> PlaceSearchRequest:
    base: dict[str, Any] = {"query": query, "language_code": "vi"}
    base.update(kwargs)
    return PlaceSearchRequest(**base)


class FakeCache:
    """Minimal in-memory fake for cache fallback paths."""

    def __init__(self, candidates: list[PlaceCandidate] | None = None, result: str = "miss") -> None:
        self._candidates = candidates
        self._result = result
        self.lookup_calls: list = []
        self.upsert_calls: list = []

    async def lookup(self, request: PlaceSearchRequest, *, ttl_seconds: int = 900):
        from agents.tools.place_cache import CacheDiagnostics
        self.lookup_calls.append(request)
        if self._result == "hit" and self._candidates:
            return self._candidates, CacheDiagnostics(
                result="hit", cache_key="fake_001"[:8], candidate_count=len(self._candidates),
            )
        return None, CacheDiagnostics(result="miss", cache_key="fake_001"[:8])

    async def upsert(self, request, candidates, *, ttl_seconds=900, source="goong_places"):
        from agents.tools.place_cache import CacheDiagnostics
        self.upsert_calls.append((request, candidates))
        return CacheDiagnostics(result="write_ok", cache_key="fake_001"[:8], candidate_count=len(candidates))

    async def ensure_table(self) -> None:
        pass

    async def close(self) -> None:
        pass


# ===========================================================================
# C1: Google Text Search endpoint contract
# ===========================================================================

class TestTextSearchEndpointContract:
    """Text Search must use POST /v1/places:searchText with correct headers."""

    @pytest.mark.asyncio
    async def test_uses_post_text_search_path(self) -> None:
        """Primary provider must POST to /v1/places:searchText."""
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        await service.text_search(_make_request("seafood"))

        assert len(client.post_calls) == 1
        path, _body, _headers = client.post_calls[0]
        assert path == TEXT_SEARCH_PATH

    @pytest.mark.asyncio
    async def test_includes_google_api_key_header(self) -> None:
        """X-Goog-Api-Key must be present for authenticated calls."""
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        await service.text_search(_make_request("seafood"))

        _path, _body, headers = client.post_calls[0]
        assert "X-Goog-Api-Key" in headers
        assert headers["X-Goog-Api-Key"] == "test-google-key-abc123"

    @pytest.mark.asyncio
    async def test_includes_field_mask_header(self) -> None:
        """X-Goog-FieldMask must be present and match configured mask."""
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        await service.text_search(_make_request("seafood"))

        _path, _body, headers = client.post_calls[0]
        assert "X-Goog-FieldMask" in headers
        assert headers["X-Goog-FieldMask"] == _DEFAULT_FIELD_MASK

    @pytest.mark.asyncio
    async def test_api_key_only_in_request_headers_not_in_result(self) -> None:
        """API key must be present server-side in headers but never in serialized result."""
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("seafood"))

        # Key in request headers — verified above
        # Key NOT in serialized result
        dump = result.model_dump_json()
        assert "test-google-key-abc123" not in dump
        assert "GOOGLE_PLACES_API_KEY" not in dump

    @pytest.mark.asyncio
    async def test_text_search_body_contains_text_query(self) -> None:
        """POST body must contain textQuery matching the user query."""
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        await service.text_search(_make_request("nhà hàng hải sản"))

        _path, body, _headers = client.post_calls[0]
        assert body["textQuery"] == "nhà hàng hải sản"

    @pytest.mark.asyncio
    async def test_text_search_body_contains_location_bias(self) -> None:
        """POST body must contain locationBias circle when location_bias is set."""
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        req = _make_request("cafe", location_bias=LatLng(lat=10.5, lng=105.0), radius_meters=3000)
        await service.text_search(req)

        _path, body, _headers = client.post_calls[0]
        assert "locationBias" in body
        assert body["locationBias"]["circle"]["center"]["latitude"] == 10.5
        assert body["locationBias"]["circle"]["center"]["longitude"] == 105.0
        assert body["locationBias"]["circle"]["radius"] == 3000

    @pytest.mark.asyncio
    async def test_text_search_body_contains_max_result_count(self) -> None:
        """POST body must contain maxResultCount."""
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        req = _make_request("cafe", max_result_count=5)
        await service.text_search(req)

        _path, body, _headers = client.post_calls[0]
        assert body["maxResultCount"] == 5

    @pytest.mark.asyncio
    async def test_text_search_body_contains_included_type(self) -> None:
        """POST body must contain includedType when set."""
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        req = _make_request("cafe", included_type="cafe")
        await service.text_search(req)

        _path, body, _headers = client.post_calls[0]
        assert body["includedType"] == "cafe"

    @pytest.mark.asyncio
    async def test_nearby_search_uses_correct_path(self) -> None:
        """Nearby Search must POST to /v1/places:searchNearby."""
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        req = PlaceNearbyRequest(
            center=LatLng(lat=10.18, lng=104.05),
            included_type="restaurant",
        )
        await service.nearby_search(req)

        assert len(client.post_calls) == 1
        path, _body, _headers = client.post_calls[0]
        assert path == NEARBY_SEARCH_PATH

    @pytest.mark.asyncio
    async def test_details_uses_correct_path(self) -> None:
        """Details must GET /v1/places/{place_id}."""
        payload = _google_place()
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        req = PlaceDetailsRequest(place_id="places/ChIJgoogle_test_place_id")
        await service.details(req)

        assert len(client.get_calls) == 1
        path, _headers = client.get_calls[0]
        assert path == f"{DETAILS_PATH}/ChIJgoogle_test_place_id"


# ===========================================================================
# C2: Field mask coverage
# ===========================================================================

class TestFieldMaskCoverage:
    """Field mask must cover every rich field consumed by normalize_place()."""

    def test_default_field_mask_is_string(self) -> None:
        assert isinstance(_DEFAULT_FIELD_MASK, str)
        assert len(_DEFAULT_FIELD_MASK) > 0

    def test_field_mask_no_secret_leakage(self) -> None:
        mask = _DEFAULT_FIELD_MASK.lower()
        assert "key" not in mask
        assert "secret" not in mask
        assert "token" not in mask
        assert "password" not in mask

    def test_field_mask_contains_core_fields(self) -> None:
        """Core fields required for basic place identification."""
        core = [
            "places.id",
            "places.displayName",
            "places.formattedAddress",
            "places.location",
        ]
        for field in core:
            assert field in _DEFAULT_FIELD_MASK, f"Missing core field: {field}"

    def test_field_mask_contains_rich_fields(self) -> None:
        """Rich fields consumed by normalize_place() and needed for S03/S04.

        T02 expanded the mask to cover every field consumed by normalize_place().
        """
        rich = [
            "places.rating",
            "places.userRatingCount",
            "places.priceLevel",
            "places.primaryType",
            "places.types",
            "places.currentOpeningHours",
            "places.regularOpeningHours",
            "places.businessStatus",
            "places.accessibilityOptions",
            "places.nationalPhoneNumber",
            "places.internationalPhoneNumber",
            "places.googleMapsUri",
            "places.websiteUri",
            "places.shortFormattedAddress",
        ]
        for field in rich:
            assert field in _DEFAULT_FIELD_MASK, f"Missing rich field: {field}"

    @pytest.mark.asyncio
    async def test_request_metadata_exposes_field_mask(self) -> None:
        """SearchPlacesToolResult.request_metadata must include the field mask."""
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("test"))

        assert "field_mask" in result.request_metadata
        assert result.request_metadata["field_mask"] == _DEFAULT_FIELD_MASK

    @pytest.mark.asyncio
    async def test_audit_exposes_field_mask(self) -> None:
        """SearchPlacesToolResult.audit must include the field mask."""
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("test"))

        assert "field_mask" in result.audit
        assert result.audit["field_mask"] == _DEFAULT_FIELD_MASK


# ===========================================================================
# C3: Rich field normalization envelope
# ===========================================================================

class TestNormalizePlaceRichFields:
    """normalize_place() must extract every rich field from Google Places (New) response."""

    def test_extracts_coordinates(self) -> None:
        candidate = normalize_place(_google_place())
        assert candidate is not None
        assert candidate.location is not None
        assert candidate.location.lat == 10.1798
        assert candidate.location.lng == 104.0498

    def test_extracts_rating_count(self) -> None:
        candidate = normalize_place(_google_place())
        assert candidate is not None
        assert candidate.user_rating_count == 321

    def test_extracts_open_now(self) -> None:
        candidate = normalize_place(_google_place())
        assert candidate is not None
        assert candidate.open_now is True

    def test_extracts_business_status(self) -> None:
        candidate = normalize_place(_google_place())
        assert candidate is not None
        assert candidate.business_status == "OPERATIONAL"

    def test_extracts_phone_numbers(self) -> None:
        candidate = normalize_place(_google_place())
        assert candidate is not None
        assert candidate.national_phone_number == "0297 3846 123"
        assert candidate.international_phone_number == "+84 297 3846 123"

    def test_extracts_website_uri(self) -> None:
        candidate = normalize_place(_google_place())
        assert candidate is not None
        assert candidate.website_uri == "https://haisanhamninh.example.com"

    def test_extracts_map_uri(self) -> None:
        candidate = normalize_place(_google_place())
        assert candidate is not None
        assert candidate.map_uri == "https://maps.google.com/?q=place_id:ChIJgoogle_test_place_id"

    def test_extracts_primary_type(self) -> None:
        candidate = normalize_place(_google_place())
        assert candidate is not None
        assert candidate.primary_type == "seafood_restaurant"

    def test_extracts_accessibility_options(self) -> None:
        candidate = normalize_place(_google_place())
        assert candidate is not None
        assert candidate.accessibility_options == {
            "wheelchairAccessibleParking": True,
            "wheelchairAccessibleEntrance": True,
        }

    def test_extracts_short_formatted_address(self) -> None:
        candidate = normalize_place(_google_place())
        assert candidate is not None
        assert candidate.short_formatted_address == "Hàm Ninh, Phú Quốc"

    def test_extracts_types_list(self) -> None:
        candidate = normalize_place(_google_place())
        assert candidate is not None
        assert "restaurant" in candidate.types
        assert "seafood_restaurant" in candidate.types

    def test_extracts_price_level_from_enum_string(self) -> None:
        candidate = normalize_place(_google_place())
        assert candidate is not None
        assert candidate.price_level == 2  # PRICE_LEVEL_MODERATE -> 2

    def test_extracts_resource_name(self) -> None:
        candidate = normalize_place(_google_place())
        assert candidate is not None
        assert candidate.resource_name == "places/ChIJgoogle_test_place_id"

    def test_extracts_display_name_from_localized_text(self) -> None:
        candidate = normalize_place(_google_place())
        assert candidate is not None
        assert candidate.display_name == "Hải Sản Hàm Ninh"

    def test_null_fields_do_not_crash(self) -> None:
        """Missing optional fields must not cause normalization to fail."""
        sparse = {
            "id": "sparse_place",
            "displayName": {"text": "Sparse Place"},
        }
        candidate = normalize_place(sparse)
        assert candidate is not None
        assert candidate.place_id == "sparse_place"
        assert candidate.location is None
        assert candidate.rating is None
        assert candidate.user_rating_count is None
        assert candidate.open_now is None
        assert candidate.business_status is None
        assert candidate.national_phone_number is None
        assert candidate.website_uri is None
        assert candidate.map_uri is None

    def test_no_place_id_returns_none(self) -> None:
        assert normalize_place({"displayName": {"text": "No ID"}}) is None

    def test_open_now_false(self) -> None:
        candidate = normalize_place(_google_place(currentOpeningHours={"openNow": False}))
        assert candidate is not None
        assert candidate.open_now is False

    def test_open_now_absent_returns_none(self) -> None:
        candidate = normalize_place(_google_place(currentOpeningHours=None))
        assert candidate is not None
        assert candidate.open_now is None

    def test_regular_opening_hours_fallback(self) -> None:
        """Some responses use regularOpeningHours instead of currentOpeningHours."""
        candidate = normalize_place(_google_place(
            currentOpeningHours=None,
            regularOpeningHours={"openNow": True},
        ))
        assert candidate is not None
        assert candidate.open_now is True

    def test_price_level_int_passthrough(self) -> None:
        candidate = normalize_place(_google_place(priceLevel=3))
        assert candidate is not None
        assert candidate.price_level == 3

    def test_fairness_tags_from_accessibility(self) -> None:
        candidate = normalize_place(_google_place(accessibilityOptions={
            "wheelchairAccessibleParking": True,
        }))
        assert candidate is not None
        assert "wheelchairAccessibleParking" in candidate.fairness_tags

    def test_fairness_tags_default_when_no_accessibility(self) -> None:
        candidate = normalize_place(_google_place(accessibilityOptions={}))
        assert candidate is not None
        assert "accessibility_unknown" in candidate.fairness_tags

    def test_route_context_computed_with_origin(self) -> None:
        origin = LatLng(lat=10.18, lng=104.05)
        candidate = normalize_place(_google_place(), origin=origin)
        assert candidate is not None
        assert candidate.route_context is not None
        assert candidate.route_context.distance_meters is not None
        assert candidate.route_context.distance_meters > 0


# ===========================================================================
# C4: Credential diagnostics
# ===========================================================================

class TestCredentialDiagnostics:
    """Missing/invalid credentials must produce honest diagnostics."""

    @pytest.mark.asyncio
    async def test_missing_key_returns_credentials_blocked(self) -> None:
        """Empty GOOGLE_PLACES_API_KEY → credentials_blocked, no HTTP call."""
        client = FakeHttpClient([])
        service = GooglePlacesService(settings=_no_key_settings(), client=client)

        result = await service.text_search(_make_request("test"))

        assert result.status == PlaceToolStatus.CREDENTIALS_BLOCKED
        assert result.source == PlaceToolSource.GOOGLE_PLACES
        assert len(client.post_calls) == 0  # No HTTP call made
        # Error code is in reasoning_log, not audit
        assert any("missing_google_api_key" in entry for entry in result.reasoning_log)

    @pytest.mark.asyncio
    async def test_missing_key_honest_error_message(self) -> None:
        """credentials_blocked must have an honest explanation in reasoning_log."""
        client = FakeHttpClient([])
        service = GooglePlacesService(settings=_no_key_settings(), client=client)

        result = await service.text_search(_make_request("test"))

        # SearchPlacesToolResult doesn't have an 'error' field;
        # diagnostics are in reasoning_log
        assert any("credential" in entry.lower() for entry in result.reasoning_log)
        assert any("not configured" in entry.lower() for entry in result.reasoning_log)

    @pytest.mark.asyncio
    async def test_missing_key_reasoning_log_explains(self) -> None:
        """reasoning_log must explain that credentials were not configured."""
        client = FakeHttpClient([])
        service = GooglePlacesService(settings=_no_key_settings(), client=client)

        result = await service.text_search(_make_request("test"))

        assert any("credential" in entry.lower() for entry in result.reasoning_log)

    @pytest.mark.asyncio
    async def test_missing_key_request_metadata_includes_endpoint(self) -> None:
        """Even credential-blocked responses must include request metadata."""
        client = FakeHttpClient([])
        service = GooglePlacesService(settings=_no_key_settings(), client=client)

        result = await service.text_search(_make_request("test"))

        assert "endpoint" in result.request_metadata
        assert "field_mask" in result.request_metadata


# ===========================================================================
# C5: Google error handling — auth, quota, timeout, malformed, 5xx
# ===========================================================================

class TestGoogleErrorHandling:
    """Each Google error type must produce honest diagnostics + cache fallback."""

    @pytest.mark.asyncio
    async def test_403_auth_error_falls_back_to_cache(self) -> None:
        """403 → circuit failure → cache fallback → UNAVAILABLE on miss."""
        cache = FakeCache(candidates=None, result="miss")
        client = FakeHttpClient([_fake_response(status_code=403)])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=cache)

        result = await service.text_search(_make_request("test"))

        # With cache miss, the error path cascades to UNAVAILABLE
        assert result.status == PlaceToolStatus.UNAVAILABLE
        assert "fallback_reason" in result.audit

    @pytest.mark.asyncio
    async def test_401_auth_error_falls_back_to_cache(self) -> None:
        """401 → circuit failure → cache fallback → UNAVAILABLE on miss."""
        cache = FakeCache(candidates=None, result="miss")
        client = FakeHttpClient([_fake_response(status_code=401)])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=cache)

        result = await service.text_search(_make_request("test"))

        assert result.status == PlaceToolStatus.UNAVAILABLE
        assert "fallback_reason" in result.audit

    @pytest.mark.asyncio
    async def test_429_quota_exceeded_falls_back_to_cache(self) -> None:
        """429 → circuit failure → cache fallback → UNAVAILABLE on miss."""
        cache = FakeCache(candidates=None, result="miss")
        client = FakeHttpClient([_fake_response(status_code=429)])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=cache)

        result = await service.text_search(_make_request("test"))

        assert result.status == PlaceToolStatus.UNAVAILABLE
        assert "fallback_reason" in result.audit

    @pytest.mark.asyncio
    async def test_timeout_falls_back_to_cache(self) -> None:
        """httpx.TimeoutException → circuit failure → cache fallback → UNAVAILABLE on miss."""
        cache = FakeCache(candidates=None, result="miss")
        client = FakeHttpClient([httpx.TimeoutException("connection timed out")])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=cache)

        result = await service.text_search(_make_request("test"))

        assert result.status == PlaceToolStatus.UNAVAILABLE
        assert "fallback_reason" in result.audit

    @pytest.mark.asyncio
    async def test_500_upstream_error_falls_back_to_cache(self) -> None:
        """500 → circuit failure → cache fallback → UNAVAILABLE on miss."""
        cache = FakeCache(candidates=None, result="miss")
        client = FakeHttpClient([_fake_response(status_code=500)])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=cache)

        result = await service.text_search(_make_request("test"))

        assert result.status == PlaceToolStatus.UNAVAILABLE
        assert "fallback_reason" in result.audit

    @pytest.mark.asyncio
    async def test_malformed_json_falls_back_to_cache(self) -> None:
        """Malformed JSON → UPSTREAM_ERROR (malformed path returns _safe_error directly,
        which then triggers circuit failure + cache fallback → UNAVAILABLE on miss)."""
        cache = FakeCache(candidates=None, result="miss")
        client = FakeHttpClient([_fake_response(json_error=ValueError("not json"))])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=cache)

        result = await service.text_search(_make_request("test"))

        # Malformed → _safe_error returns UPSTREAM_ERROR directly,
        # then _execute_search calls fallback_from_cache → UNAVAILABLE
        assert result.status == PlaceToolStatus.UNAVAILABLE
        assert "fallback_reason" in result.audit

    @pytest.mark.asyncio
    async def test_malformed_payload_shape_returns_upstream_error(self) -> None:
        """200 but no 'places' key → _safe_error returns UPSTREAM_ERROR directly
        (malformed path does NOT trigger cache fallback — protocol error, not transient)."""
        cache = FakeCache(candidates=None, result="miss")
        client = FakeHttpClient([_fake_response(payload={"weird": "shape"})])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=cache)

        result = await service.text_search(_make_request("test"))

        # Malformed shape → _extract_places_list returns None → _safe_error UPSTREAM_ERROR
        # (malformed is a protocol error, not transient — no cache fallback)
        assert result.status == PlaceToolStatus.UPSTREAM_ERROR

    @pytest.mark.asyncio
    async def test_google_error_envelope_in_response_body(self) -> None:
        """200 with error envelope: status=REQUEST_DENIED → auth error → cache fallback."""
        cache = FakeCache(candidates=None, result="miss")
        client = FakeHttpClient([_fake_response(payload={
            "error": {
                "status": "REQUEST_DENIED",
                "message": "API key not valid. Please pass a valid API key.",
            }
        })])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=cache)

        result = await service.text_search(_make_request("test"))

        # Auth error → circuit failure → cache fallback → UNAVAILABLE
        assert result.status == PlaceToolStatus.UNAVAILABLE
        assert "fallback_reason" in result.audit

    @pytest.mark.asyncio
    async def test_google_quota_envelope_in_response_body(self) -> None:
        """200 with error envelope: status=RESOURCE_EXHAUSTED → quota → cache fallback."""
        cache = FakeCache(candidates=None, result="miss")
        client = FakeHttpClient([_fake_response(payload={
            "error": {
                "status": "RESOURCE_EXHAUSTED",
                "message": "You have exceeded your daily quota.",
            }
        })])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=cache)

        result = await service.text_search(_make_request("test"))

        # Quota error → circuit failure → cache fallback → UNAVAILABLE
        assert result.status == PlaceToolStatus.UNAVAILABLE
        assert "fallback_reason" in result.audit

    # -- Error handling with NO cache (error still cascades to UNAVAILABLE) --

    @pytest.mark.asyncio
    async def test_403_without_cache_returns_unavailable(self) -> None:
        """403 with no cache → error result → _fallback_from_cache(None) → UNAVAILABLE."""
        client = FakeHttpClient([_fake_response(status_code=403)])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=None)

        result = await service.text_search(_make_request("test"))

        # Error result triggers _fallback_from_cache → no cache → UNAVAILABLE
        assert result.status == PlaceToolStatus.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_timeout_without_cache_returns_unavailable(self) -> None:
        """Timeout with no cache → error result → _fallback_from_cache(None) → UNAVAILABLE."""
        client = FakeHttpClient([httpx.TimeoutException("timeout")])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=None)

        result = await service.text_search(_make_request("test"))

        # Error result triggers _fallback_from_cache → no cache → UNAVAILABLE
        assert result.status == PlaceToolStatus.UNAVAILABLE


# ===========================================================================
# C6: Secret / raw payload redaction
# ===========================================================================

class TestSecretRedaction:
    """No secrets, API keys, raw payloads, or sensitive data in any response."""

    @pytest.mark.asyncio
    async def test_no_api_key_in_ok_response(self) -> None:
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("test"))
        dump = result.model_dump_json()

        assert "test-google-key-abc123" not in dump
        assert "GOOGLE_PLACES_API_KEY" not in dump

    @pytest.mark.asyncio
    async def test_no_api_key_in_error_response(self) -> None:
        cache = FakeCache()
        client = FakeHttpClient([httpx.TimeoutException("timeout")])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=cache)

        result = await service.text_search(_make_request("test"))
        dump = result.model_dump_json()

        assert "test-google-key-abc123" not in dump

    @pytest.mark.asyncio
    async def test_no_raw_provider_payload_in_serialization(self) -> None:
        """Serialized result must not contain raw provider JSON."""
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("test"))
        dump = result.model_dump_json()

        assert "raw" not in dump.lower()
        assert "payload" not in dump.lower()

    @pytest.mark.asyncio
    async def test_no_phone_numbers_in_audit_or_metadata(self) -> None:
        """Phone numbers must not appear in audit/metadata fields."""
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("test"))

        audit_str = json.dumps(result.audit).lower()
        metadata_str = json.dumps(result.request_metadata).lower()
        assert "0297" not in audit_str
        assert "0297" not in metadata_str
        assert "+84" not in audit_str
        assert "+84" not in metadata_str

    @pytest.mark.asyncio
    async def test_no_secrets_in_reasoning_log(self) -> None:
        """reasoning_log must not contain API keys or raw payloads."""
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("test"))
        combined = " ".join(result.reasoning_log).lower()

        assert "test-google-key" not in combined
        assert "api_key" not in combined
        assert "secret" not in combined

    @pytest.mark.asyncio
    async def test_extra_fields_forbidden_on_result(self) -> None:
        """SearchPlacesToolResult must reject extra fields (no raw_payload leakage)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SearchPlacesToolResult(
                status=PlaceToolStatus.OK,
                source=PlaceToolSource.GOOGLE_PLACES,
                raw_provider_payload={"secret": True},
            )


# ===========================================================================
# C7: Goong fallback seam — honest fallback, not silent primary
# ===========================================================================

class TestGoongFallbackSeam:
    """When Google is unavailable, Goong fallback must be honest about its source."""

    @pytest.mark.asyncio
    async def test_google_unavailable_cache_miss_produces_honest_unavailable(self) -> None:
        """Google timeout + cache miss → UNAVAILABLE, no fake results."""
        cache = FakeCache(candidates=None, result="miss")
        client = FakeHttpClient([httpx.TimeoutException("timeout")])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=cache)

        result = await service.text_search(_make_request("test"))

        assert result.status == PlaceToolStatus.UNAVAILABLE
        assert result.candidates == []
        # Must reveal why provider was unavailable
        assert "fallback_reason" in result.audit

    @pytest.mark.asyncio
    async def test_google_unavailable_cache_hit_shows_cache_source(self) -> None:
        """Google timeout + cache hit → OK with source=cache, not google_places."""
        cached = [PlaceCandidate(place_id="places/cached_goong", display_name="Cached Goong Place", types=["restaurant"])]
        cache = FakeCache(candidates=cached, result="hit")
        client = FakeHttpClient([httpx.TimeoutException("timeout")])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=cache)

        result = await service.text_search(_make_request("test"))

        assert result.status == PlaceToolStatus.OK
        assert result.source == PlaceToolSource.CACHE
        assert result.candidates[0].place_id == "places/cached_goong"
        # Must warn about provider being unavailable
        assert any("provider" in w.lower() and "unavailable" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_credential_blocked_does_not_silently_fallback_to_goong(self) -> None:
        """Missing Google key → credentials_blocked, NOT silent Goong fallback."""
        client = FakeHttpClient([])
        service = GooglePlacesService(settings=_no_key_settings(), client=client)

        result = await service.text_search(_make_request("test"))

        assert result.status == PlaceToolStatus.CREDENTIALS_BLOCKED
        assert result.source == PlaceToolSource.GOOGLE_PLACES
        # Must NOT return goong_places source silently
        assert result.source != PlaceToolSource.GOONG_PLACES

    @pytest.mark.asyncio
    async def test_audit_includes_fallback_reason_on_provider_failure(self) -> None:
        """Provider failure path must include fallback_reason in audit."""
        cache = FakeCache(candidates=None, result="miss")
        client = FakeHttpClient([httpx.TimeoutException("timeout")])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=cache)

        result = await service.text_search(_make_request("test"))

        assert "fallback_reason" in result.audit
        assert "provider" in result.audit["fallback_reason"]

    @pytest.mark.asyncio
    async def test_audit_includes_fallback_source_on_cache_hit(self) -> None:
        """Cache-hit fallback must include fallback_source=cache in audit."""
        cached = [PlaceCandidate(place_id="places/cached", display_name="Cached", types=["restaurant"])]
        cache = FakeCache(candidates=cached, result="hit")
        client = FakeHttpClient([httpx.TimeoutException("timeout")])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=cache)

        result = await service.text_search(_make_request("test"))

        assert result.audit.get("fallback_source") == "cache"


# ===========================================================================
# C8: Request metadata — endpoint, field mask, credential status
# ===========================================================================

class TestRequestMetadata:
    """request_metadata must always report endpoint, field mask, and limits."""

    @pytest.mark.asyncio
    async def test_ok_response_has_endpoint(self) -> None:
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("test"))

        assert result.request_metadata["endpoint"] == "google_text_search"

    @pytest.mark.asyncio
    async def test_ok_response_has_language_code(self) -> None:
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("test", language_code="en"))

        assert result.request_metadata["language_code"] == "en"

    @pytest.mark.asyncio
    async def test_ok_response_has_max_result_count(self) -> None:
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("test", max_result_count=5))

        assert result.request_metadata["max_result_count"] == 5

    @pytest.mark.asyncio
    async def test_credential_blocked_response_has_metadata(self) -> None:
        client = FakeHttpClient([])
        service = GooglePlacesService(settings=_no_key_settings(), client=client)

        result = await service.text_search(_make_request("test"))

        assert "endpoint" in result.request_metadata
        assert "field_mask" in result.request_metadata

    @pytest.mark.asyncio
    async def test_nearby_search_metadata_has_correct_endpoint(self) -> None:
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        req = PlaceNearbyRequest(center=LatLng(lat=10.18, lng=104.05), included_type="cafe")
        result = await service.nearby_search(req)

        assert result.request_metadata["endpoint"] == "google_nearby_search"

    @pytest.mark.asyncio
    async def test_ok_response_has_provider_contract_version(self) -> None:
        """OK response must include stable provider contract version."""
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("test"))

        assert "provider_contract_version" in result.request_metadata
        assert result.request_metadata["provider_contract_version"] == "v1"

    @pytest.mark.asyncio
    async def test_ok_response_has_credential_status_live(self) -> None:
        """With a valid key, credential_status must be 'live'."""
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("test"))

        assert result.request_metadata["credential_status"] == "live"

    @pytest.mark.asyncio
    async def test_credential_blocked_has_credential_status_blocked(self) -> None:
        """Missing key → credential_status='blocked' in request_metadata."""
        client = FakeHttpClient([])
        service = GooglePlacesService(settings=_no_key_settings(), client=client)

        result = await service.text_search(_make_request("test"))

        assert result.request_metadata["credential_status"] == "blocked"

    @pytest.mark.asyncio
    async def test_ok_response_has_provider_attempted(self) -> None:
        """OK response must identify which provider was attempted."""
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("test"))

        assert result.request_metadata["provider_attempted"] == "google_places"

    @pytest.mark.asyncio
    async def test_ok_response_has_result_count(self) -> None:
        """OK response must include result_count matching candidates."""
        payload = {"places": [_google_place(), _google_place(id="second")]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("test"))

        assert result.request_metadata["result_count"] == 2

    @pytest.mark.asyncio
    async def test_unavailable_response_has_full_metadata(self) -> None:
        """UNAVAILABLE responses must include all enriched diagnostic keys."""
        cache = FakeCache(candidates=None, result="miss")
        client = FakeHttpClient([httpx.TimeoutException("timeout")])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=cache)

        result = await service.text_search(_make_request("test"))

        meta = result.request_metadata
        assert "field_mask" in meta
        assert "credential_status" in meta
        assert "provider_attempted" in meta
        assert "fallback_reason" in meta
        assert "result_count" in meta
        assert meta["result_count"] == 0
        assert "provider_contract_version" in meta


# ===========================================================================
# C9: Provider attempt order — Google must be primary
# ===========================================================================

class TestProviderAttemptOrder:
    """Google must be attempted first; Goong/cache only as fallback."""

    @pytest.mark.asyncio
    async def test_google_attempted_before_cache_fallback(self) -> None:
        """On provider timeout, cache lookup happens AFTER the Google call."""
        cache = FakeCache(candidates=None, result="miss")
        client = FakeHttpClient([httpx.TimeoutException("timeout")])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=cache)

        await service.text_search(_make_request("test"))

        # Google was called (post_calls populated)
        assert len(client.post_calls) >= 1
        # Cache was consulted after the failure
        assert len(cache.lookup_calls) >= 1

    @pytest.mark.asyncio
    async def test_google_not_called_when_credentials_missing(self) -> None:
        """No credentials → no Google HTTP call at all."""
        client = FakeHttpClient([])
        service = GooglePlacesService(settings=_no_key_settings(), client=client)

        await service.text_search(_make_request("test"))

        assert len(client.post_calls) == 0

    @pytest.mark.asyncio
    async def test_circuit_open_skips_google(self) -> None:
        """Circuit open → Google call skipped, cache used directly."""
        cache = FakeCache(
            candidates=[PlaceCandidate(place_id="p1", display_name="P1", types=["restaurant"])],
            result="hit",
        )
        circuit = CircuitState(failure_threshold=1)
        circuit.record_failure()  # force open

        client = FakeHttpClient([_fake_response(payload={"places": [_google_place()]})])
        service = GooglePlacesService(settings=_settings(), client=client, place_cache=cache, circuit=circuit)

        await service.text_search(_make_request("test"))

        # Google should NOT have been called
        assert len(client.post_calls) == 0
        # Cache should have been used
        assert len(cache.lookup_calls) >= 1


# ===========================================================================
# C10: Service-level contract — full OK response envelope
# ===========================================================================

class TestServiceOkResponseEnvelope:
    """A successful Google Places response must produce a complete SearchPlacesToolResult."""

    @pytest.mark.asyncio
    async def test_ok_status_and_source(self) -> None:
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("seafood"))

        assert result.status == PlaceToolStatus.OK
        assert result.source == PlaceToolSource.GOOGLE_PLACES

    @pytest.mark.asyncio
    async def test_candidates_populated(self) -> None:
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("seafood"))

        assert len(result.candidates) == 1
        assert result.candidates[0].display_name == "Hải Sản Hàm Ninh"

    @pytest.mark.asyncio
    async def test_interpreted_query_preserved(self) -> None:
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("nhà hàng hải sản"))

        assert result.interpreted_query == "nhà hàng hải sản"

    @pytest.mark.asyncio
    async def test_reasoning_log_shows_normalization(self) -> None:
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("seafood"))

        assert any("normalized" in entry.lower() for entry in result.reasoning_log)

    @pytest.mark.asyncio
    async def test_place_recommendation_status_populated(self) -> None:
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("seafood"))

        assert result.place_recommendation_status.provider_places_returned == 1
        assert result.place_recommendation_status.candidates_after_normalization == 1

    @pytest.mark.asyncio
    async def test_retrieved_at_is_recent(self) -> None:
        payload = {"places": [_google_place()]}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("seafood"))

        assert result.retrieved_at is not None
        assert result.retrieved_at.tzinfo is not None

    @pytest.mark.asyncio
    async def test_empty_places_returns_empty_status(self) -> None:
        payload = {"places": []}
        client = FakeHttpClient([_fake_response(payload=payload)])
        service = GooglePlacesService(settings=_settings(), client=client)

        result = await service.text_search(_make_request("nonexistent"))

        assert result.status == PlaceToolStatus.EMPTY
        assert result.candidates == []


# ===========================================================================
# C11: Negative tests — invalid request bounds
# ===========================================================================

class TestInvalidRequestBounds:
    """Invalid request bounds must be rejected at the model level before reaching Google."""

    def test_query_too_short_rejected(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PlaceSearchRequest(query="")

    def test_query_too_long_rejected(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PlaceSearchRequest(query="x" * 161)

    def test_radius_too_small_rejected(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PlaceSearchRequest(query="test", radius_meters=0)

    def test_radius_too_large_rejected(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PlaceSearchRequest(query="test", radius_meters=50_001)

    def test_max_result_count_too_large_rejected(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PlaceSearchRequest(query="test", max_result_count=21)

    def test_max_result_count_zero_rejected(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PlaceSearchRequest(query="test", max_result_count=0)

    def test_extra_fields_rejected(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PlaceSearchRequest(query="test", secret_key="leak")
