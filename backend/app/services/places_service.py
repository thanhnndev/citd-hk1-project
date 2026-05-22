"""Google Places API (New) client seam and safe normalization service."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from app.core.config import Settings, get_settings
from app.models.places import (
    PlaceCandidate,
    PlaceDetailsRequest,
    PlaceNearbyRequest,
    PlaceSearchRequest,
    PlaceToolError,
    PlaceToolResponse,
    PlaceToolSource,
    PlaceToolStatus,
    RouteContext,
)
from app.models.request import LatLng

logger = logging.getLogger(__name__)

PLACES_BASE_URL = "https://places.googleapis.com/v1"
TEXT_SEARCH_PATH = "/places:searchText"
NEARBY_SEARCH_PATH = "/places:searchNearby"
DETAILS_PATH_TEMPLATE = "/places/{place_id}"

PLACE_FIELD_MASKS = {
    "search": ",".join(
        [
            "places.id",
            "places.name",
            "places.displayName",
            "places.types",
            "places.primaryType",
            "places.formattedAddress",
            "places.shortFormattedAddress",
            "places.location",
            "places.rating",
            "places.userRatingCount",
            "places.priceLevel",
            "places.currentOpeningHours.openNow",
            "places.businessStatus",
            "places.accessibilityOptions",
            "places.nationalPhoneNumber",
            "places.internationalPhoneNumber",
            "places.websiteUri",
            "places.googleMapsUri",
        ]
    ),
    "details": ",".join(
        [
            "id",
            "name",
            "displayName",
            "types",
            "primaryType",
            "formattedAddress",
            "shortFormattedAddress",
            "location",
            "rating",
            "userRatingCount",
            "priceLevel",
            "currentOpeningHours.openNow",
            "businessStatus",
            "accessibilityOptions",
            "nationalPhoneNumber",
            "internationalPhoneNumber",
            "websiteUri",
            "googleMapsUri",
        ]
    ),
}

_PRICE_LEVELS = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}


class PlacesHttpClient(Protocol):
    """Minimal async HTTP seam so tests and agents can substitute a mock client."""

    async def post(self, path: str, *, json: Mapping[str, Any], headers: Mapping[str, str]) -> Any: ...

    async def get(self, path: str, *, headers: Mapping[str, str], params: Mapping[str, str] | None = None) -> Any: ...


class HttpxPlacesClient:
    """Thin httpx-backed client for Google Places API (New)."""

    def __init__(self, *, base_url: str = PLACES_BASE_URL, timeout: float = 8.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def post(self, path: str, *, json: Mapping[str, Any], headers: Mapping[str, str]) -> httpx.Response:
        return await self._client.post(path, json=json, headers=headers)

    async def get(
        self, path: str, *, headers: Mapping[str, str], params: Mapping[str, str] | None = None
    ) -> httpx.Response:
        return await self._client.get(path, headers=headers, params=params)

    async def aclose(self) -> None:
        await self._client.aclose()


class GooglePlacesService:
    """Server-side Places service returning normalized candidates and safe envelopes."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: PlacesHttpClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or HttpxPlacesClient()

    async def text_search(self, request: PlaceSearchRequest) -> PlaceToolResponse:
        body = {
            "textQuery": request.query,
            "languageCode": request.language_code,
            "maxResultCount": request.max_result_count,
            "locationBias": {
                "circle": {
                    "center": {"latitude": request.location_bias.lat, "longitude": request.location_bias.lng},
                    "radius": float(request.radius_meters),
                }
            },
        }
        if request.included_type:
            body["includedType"] = request.included_type
        return await self._execute(
            operation="text_search",
            request=request,
            field_mask=PLACE_FIELD_MASKS["search"],
            call=lambda headers: self._client.post(TEXT_SEARCH_PATH, json=body, headers=headers),
            origin=request.location_bias,
        )

    async def nearby_search(self, request: PlaceNearbyRequest) -> PlaceToolResponse:
        body = {
            "includedTypes": [request.included_type],
            "languageCode": request.language_code,
            "maxResultCount": request.max_result_count,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": request.center.lat, "longitude": request.center.lng},
                    "radius": float(request.radius_meters),
                }
            },
        }
        return await self._execute(
            operation="nearby_search",
            request=request,
            field_mask=PLACE_FIELD_MASKS["search"],
            call=lambda headers: self._client.post(NEARBY_SEARCH_PATH, json=body, headers=headers),
            origin=request.center,
        )

    async def details(self, request: PlaceDetailsRequest) -> PlaceToolResponse:
        place_id = request.place_id.removeprefix("places/")
        path = DETAILS_PATH_TEMPLATE.format(place_id=place_id)
        return await self._execute(
            operation="details",
            request=request,
            field_mask=PLACE_FIELD_MASKS["details"],
            call=lambda headers: self._client.get(path, headers=headers, params={"languageCode": request.language_code}),
        )

    async def _execute(self, *, operation: str, request: Any, field_mask: str, call: Any, origin: LatLng | None = None) -> PlaceToolResponse:
        retrieved_at = datetime.now(UTC)
        api_key = self._settings.GOOGLE_PLACES_API_KEY.strip()
        if not api_key:
            return self._response(
                status=PlaceToolStatus.CREDENTIALS_BLOCKED,
                request=request,
                retrieved_at=retrieved_at,
                error=PlaceToolError(
                    code="missing_google_places_api_key",
                    message="Google Places credentials are not configured.",
                    retryable=False,
                ),
                field_mask=field_mask,
            )

        headers = {
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": field_mask,
            "Content-Type": "application/json",
        }
        try:
            response = await call(headers)
        except httpx.TimeoutException:
            logger.warning("google_places_timeout", extra={"operation": operation})
            return self._safe_error(request, retrieved_at, field_mask, PlaceToolStatus.UPSTREAM_ERROR, "timeout", "Google Places request timed out.", True)
        except Exception as exc:  # noqa: BLE001 - service boundary must sanitize all provider/client failures.
            logger.warning("google_places_client_error", extra={"operation": operation, "error_type": type(exc).__name__})
            return self._safe_error(request, retrieved_at, field_mask, PlaceToolStatus.UPSTREAM_ERROR, "upstream_error", "Google Places request failed.", True)

        status_code = getattr(response, "status_code", 200)
        if status_code in (401, 403):
            return self._safe_error(request, retrieved_at, field_mask, PlaceToolStatus.UPSTREAM_ERROR, "auth_error", "Google Places rejected the configured credentials.", False)
        if status_code == 429:
            return self._safe_error(request, retrieved_at, field_mask, PlaceToolStatus.UPSTREAM_ERROR, "quota_exceeded", "Google Places quota was exceeded or rate limited.", True)
        if status_code >= 500:
            logger.warning("google_places_upstream_5xx", extra={"operation": operation, "status_code": status_code})
            return self._safe_error(request, retrieved_at, field_mask, PlaceToolStatus.UPSTREAM_ERROR, "upstream_error", "Google Places returned an upstream error.", True)
        if status_code >= 400:
            return self._safe_error(request, retrieved_at, field_mask, PlaceToolStatus.UPSTREAM_ERROR, "upstream_error", "Google Places request was not accepted.", False)

        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            logger.warning("google_places_malformed_json", extra={"operation": operation})
            return self._safe_error(request, retrieved_at, field_mask, PlaceToolStatus.UPSTREAM_ERROR, "malformed_response", "Google Places returned malformed data.", True)

        raw_places = payload.get("places") if isinstance(payload, dict) else None
        if raw_places is None and isinstance(payload, dict) and operation == "details":
            raw_places = [payload]
        if not isinstance(raw_places, list):
            return self._safe_error(request, retrieved_at, field_mask, PlaceToolStatus.UPSTREAM_ERROR, "malformed_response", "Google Places returned an unexpected response shape.", True)

        candidates = [candidate for place in raw_places if isinstance(place, dict) and (candidate := normalize_place(place, origin=origin))]
        if not candidates:
            return self._response(status=PlaceToolStatus.EMPTY, request=request, retrieved_at=retrieved_at, field_mask=field_mask)
        return self._response(status=PlaceToolStatus.OK, request=request, retrieved_at=retrieved_at, field_mask=field_mask, candidates=candidates)

    def _safe_error(self, request: Any, retrieved_at: datetime, field_mask: str, status: PlaceToolStatus, code: str, message: str, retryable: bool) -> PlaceToolResponse:
        return self._response(
            status=status,
            request=request,
            retrieved_at=retrieved_at,
            field_mask=field_mask,
            error=PlaceToolError(code=code, message=message, retryable=retryable),
        )

    def _response(self, *, status: PlaceToolStatus, request: Any, retrieved_at: datetime, field_mask: str, candidates: list[PlaceCandidate] | None = None, error: PlaceToolError | None = None) -> PlaceToolResponse:
        return PlaceToolResponse(
            status=status,
            source=PlaceToolSource.GOOGLE_PLACES_NEW,
            request=request,
            retrieved_at=retrieved_at,
            candidates=candidates or [],
            error=error,
            metadata={"field_mask": field_mask},
        )


def normalize_place(place: Mapping[str, Any], *, origin: LatLng | None = None) -> PlaceCandidate | None:
    """Normalize one Google Places API (New) place object without leaking raw payloads."""

    place_id = _string(place.get("id")) or _resource_id(place.get("name"))
    display_name = _display_name(place.get("displayName")) or _string(place.get("formattedAddress")) or place_id
    if not place_id or not display_name:
        return None

    location = _location(place.get("location"))
    distance_meters = _int(place.get("distanceMeters"))
    if distance_meters is None and origin and location:
        distance_meters = _haversine_meters(origin, location)

    accessibility = place.get("accessibilityOptions") if isinstance(place.get("accessibilityOptions"), Mapping) else {}
    accessibility_tags = [key for key, value in accessibility.items() if value is True]

    return PlaceCandidate(
        place_id=place_id,
        resource_name=_string(place.get("name")),
        display_name=display_name,
        types=[item for item in place.get("types", []) if isinstance(item, str)],
        primary_type=_string(place.get("primaryType")),
        formatted_address=_string(place.get("formattedAddress")),
        short_formatted_address=_string(place.get("shortFormattedAddress")),
        location=location,
        rating=_float(place.get("rating")),
        user_rating_count=_int(place.get("userRatingCount")),
        price_level=_price_level(place.get("priceLevel")),
        open_now=_open_now(place),
        business_status=_string(place.get("businessStatus")),
        accessibility_options=dict(accessibility),
        national_phone_number=_string(place.get("nationalPhoneNumber")),
        international_phone_number=_string(place.get("internationalPhoneNumber")),
        google_maps_uri=_string(place.get("googleMapsUri")),
        website_uri=_string(place.get("websiteUri")),
        fairness_tags=accessibility_tags or ["accessibility_unknown"],
        route_context=RouteContext(origin=origin, distance_meters=distance_meters) if distance_meters is not None else None,
    )


def _display_name(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return _string(value.get("text"))
    return _string(value)


def _resource_id(value: Any) -> str | None:
    text = _string(value)
    if text and text.startswith("places/"):
        return text.removeprefix("places/")
    return text


def _location(value: Any) -> LatLng | None:
    if not isinstance(value, Mapping):
        return None
    lat = value.get("latitude", value.get("lat"))
    lng = value.get("longitude", value.get("lng"))
    if lat is None or lng is None:
        return None
    return LatLng(lat=float(lat), lng=float(lng))


def _open_now(place: Mapping[str, Any]) -> bool | None:
    opening_hours = place.get("currentOpeningHours")
    if isinstance(opening_hours, Mapping) and isinstance(opening_hours.get("openNow"), bool):
        return opening_hours["openNow"]
    return None


def _price_level(value: Any) -> int | None:
    if isinstance(value, int):
        return value if 0 <= value <= 4 else None
    if isinstance(value, str):
        if value.isdigit():
            parsed = int(value)
            return parsed if 0 <= parsed <= 4 else None
        return _PRICE_LEVELS.get(value)
    return None


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _haversine_meters(origin: LatLng, destination: LatLng) -> int:
    radius_m = 6_371_000
    lat1 = math.radians(origin.lat)
    lat2 = math.radians(destination.lat)
    delta_lat = math.radians(destination.lat - origin.lat)
    delta_lng = math.radians(destination.lng - origin.lng)
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    return round(radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))
