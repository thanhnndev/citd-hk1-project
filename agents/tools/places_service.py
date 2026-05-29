"""Goong Places API client seam and safe normalization service."""

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

PLACES_BASE_URL = "https://rsapi.goong.io"
AUTOCOMPLETE_PATH = "/Place/AutoComplete"
TEXT_SEARCH_PATH = "/Place/TextSearch"
DETAILS_PATH = "/Place/Detail"

_GOONG_STATUS_OK = {"OK", "ZERO_RESULTS"}
_UPSTREAM_AUTH_CODES = {"REQUEST_DENIED", "INVALID_REQUEST"}
_UPSTREAM_RATE_LIMIT_CODES = {"OVER_QUERY_LIMIT"}


class PlacesHttpClient(Protocol):
    """Minimal async HTTP seam so tests and agents can substitute a mock client."""

    async def get(self, path: str, *, params: Mapping[str, Any]) -> Any: ...


class HttpxPlacesClient:
    """Thin httpx-backed client for Goong Places REST endpoints."""

    def __init__(self, *, base_url: str = PLACES_BASE_URL, timeout: float = 8.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def get(self, path: str, *, params: Mapping[str, Any]) -> httpx.Response:
        return await self._client.get(path, params=params)

    async def aclose(self) -> None:
        await self._client.aclose()


class GoongPlacesService:
    """Server-side Goong Places service returning normalized candidates and safe envelopes."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: PlacesHttpClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or HttpxPlacesClient()

    async def text_search(self, request: PlaceSearchRequest) -> PlaceToolResponse:
        params = self._base_params(request.language_code)
        params.update(
            {
                "input": request.query,
                "location": _location_param(request.location_bias),
                "radius": request.radius_meters,
                "limit": request.max_result_count,
            }
        )
        if request.included_type:
            params["types"] = request.included_type
        return await self._execute_search(
            operation="text_search",
            request=request,
            params=params,
            origin=request.location_bias,
            metadata={"endpoint": "goong_text_search", "radius_meters": request.radius_meters},
        )

    async def nearby_search(self, request: PlaceNearbyRequest) -> PlaceToolResponse:
        params = self._base_params(request.language_code)
        params.update(
            {
                "input": request.included_type,
                "location": _location_param(request.center),
                "radius": request.radius_meters,
                "limit": request.max_result_count,
                "types": request.included_type,
            }
        )
        return await self._execute_search(
            operation="nearby_search",
            request=request,
            params=params,
            origin=request.center,
            metadata={
                "endpoint": "goong_autocomplete_nearby_approximation",
                "center": _location_param(request.center),
                "radius_meters": request.radius_meters,
                "included_type": request.included_type,
            },
        )

    async def details(self, request: PlaceDetailsRequest) -> PlaceToolResponse:
        params = self._base_params(request.language_code)
        params["place_id"] = request.place_id.removeprefix("places/")
        return await self._execute_details(operation="details", request=request, params=params)

    def _base_params(self, language_code: str) -> dict[str, Any]:
        return {"api_key": self._settings.GOONG_API_KEY.strip(), "language": language_code}

    async def _execute_search(
        self,
        *,
        operation: str,
        request: PlaceSearchRequest | PlaceNearbyRequest,
        params: Mapping[str, Any],
        origin: LatLng,
        metadata: dict[str, Any],
    ) -> PlaceToolResponse:
        retrieved_at = datetime.now(UTC)
        if not params.get("api_key"):
            return self._credential_error(request, retrieved_at, metadata)

        response_payload = await self._request_payload(operation, TEXT_SEARCH_PATH, params, request, retrieved_at, metadata)
        if isinstance(response_payload, PlaceToolResponse):
            return response_payload

        status_response = self._status_response(response_payload, request, retrieved_at, metadata)
        if status_response:
            return status_response

        raw_results = _extract_result_list(response_payload)
        if raw_results is None:
            return self._safe_error(request, retrieved_at, metadata, "malformed_response", "Goong Places returned an unexpected response shape.", True)

        candidates: list[PlaceCandidate] = []
        for raw_place in raw_results[: request.max_result_count]:
            if not isinstance(raw_place, Mapping):
                continue
            candidate = normalize_place(raw_place, origin=origin)
            if candidate and candidate.location is None and candidate.place_id:
                detail = await self._detail_candidate(candidate.place_id, request.language_code, origin=origin)
                candidate = detail or candidate
            if candidate:
                candidates.append(candidate)

        if not candidates:
            return self._response(status=PlaceToolStatus.EMPTY, request=request, retrieved_at=retrieved_at, metadata={**metadata, "error_code": "no_results"})
        return self._response(status=PlaceToolStatus.OK, request=request, retrieved_at=retrieved_at, metadata=metadata, candidates=candidates)

    async def _execute_details(self, *, operation: str, request: PlaceDetailsRequest, params: Mapping[str, Any]) -> PlaceToolResponse:
        retrieved_at = datetime.now(UTC)
        metadata = {"endpoint": "goong_detail"}
        if not params.get("api_key"):
            return self._credential_error(request, retrieved_at, metadata)

        response_payload = await self._request_payload(operation, DETAILS_PATH, params, request, retrieved_at, metadata)
        if isinstance(response_payload, PlaceToolResponse):
            return response_payload

        status_response = self._status_response(response_payload, request, retrieved_at, metadata)
        if status_response:
            return status_response

        raw_place = _extract_detail_object(response_payload)
        if raw_place is None:
            return self._safe_error(request, retrieved_at, metadata, "malformed_response", "Goong Places returned an unexpected response shape.", True)
        candidate = normalize_place(raw_place)
        if not candidate:
            return self._response(status=PlaceToolStatus.EMPTY, request=request, retrieved_at=retrieved_at, metadata={**metadata, "error_code": "no_results"})
        return self._response(status=PlaceToolStatus.OK, request=request, retrieved_at=retrieved_at, metadata=metadata, candidates=[candidate])

    async def _detail_candidate(self, place_id: str, language_code: str, *, origin: LatLng) -> PlaceCandidate | None:
        params = self._base_params(language_code)
        if not params["api_key"]:
            return None
        params["place_id"] = place_id
        try:
            response = await self._client.get(DETAILS_PATH, params=params)
            if getattr(response, "status_code", 200) >= 400:
                return None
            payload = response.json()
        except Exception:  # noqa: BLE001 - best-effort hydration must not fail the search envelope.
            logger.warning("goong_places_detail_hydration_failed", extra={"place_id_present": bool(place_id)})
            return None
        if not isinstance(payload, Mapping) or payload.get("status") not in _GOONG_STATUS_OK:
            return None
        raw_place = _extract_detail_object(payload)
        return normalize_place(raw_place, origin=origin) if raw_place else None

    async def _request_payload(
        self,
        operation: str,
        path: str,
        params: Mapping[str, Any],
        request: Any,
        retrieved_at: datetime,
        metadata: dict[str, Any],
    ) -> Mapping[str, Any] | PlaceToolResponse:
        try:
            response = await self._client.get(path, params=params)
        except httpx.TimeoutException:
            logger.warning("goong_places_timeout", extra={"operation": operation})
            return self._safe_error(request, retrieved_at, metadata, "timeout", "Goong Places request timed out.", True)
        except Exception as exc:  # noqa: BLE001 - service boundary must sanitize all provider/client failures.
            logger.warning("goong_places_client_error", extra={"operation": operation, "error_type": type(exc).__name__})
            return self._safe_error(request, retrieved_at, metadata, "upstream_error", "Goong Places request failed.", True)

        status_code = getattr(response, "status_code", 200)
        if status_code in (401, 403):
            return self._safe_error(request, retrieved_at, metadata, "auth_error", "Goong Places rejected the configured credentials.", False)
        if status_code == 429:
            return self._safe_error(request, retrieved_at, metadata, "quota_exceeded", "Goong Places quota was exceeded or rate limited.", True)
        if status_code >= 500:
            logger.warning("goong_places_upstream_5xx", extra={"operation": operation, "status_code": status_code})
            return self._safe_error(request, retrieved_at, metadata, "upstream_error", "Goong Places returned an upstream error.", True)
        if status_code >= 400:
            return self._safe_error(request, retrieved_at, metadata, "upstream_error", "Goong Places request was not accepted.", False)

        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            logger.warning("goong_places_malformed_json", extra={"operation": operation})
            return self._safe_error(request, retrieved_at, metadata, "malformed_response", "Goong Places returned malformed data.", True)
        if not isinstance(payload, Mapping):
            return self._safe_error(request, retrieved_at, metadata, "malformed_response", "Goong Places returned an unexpected response shape.", True)
        return payload

    def _status_response(self, payload: Mapping[str, Any], request: Any, retrieved_at: datetime, metadata: dict[str, Any]) -> PlaceToolResponse | None:
        status = _string(payload.get("status"))
        if not status or status in _GOONG_STATUS_OK:
            return None
        if status in _UPSTREAM_AUTH_CODES:
            return self._safe_error(request, retrieved_at, metadata, "auth_error", "Goong Places rejected the request or credentials.", False)
        if status in _UPSTREAM_RATE_LIMIT_CODES:
            return self._safe_error(request, retrieved_at, metadata, "quota_exceeded", "Goong Places quota was exceeded or rate limited.", True)
        return self._safe_error(request, retrieved_at, metadata, "upstream_error", "Goong Places returned an upstream error.", True)

    def _credential_error(self, request: Any, retrieved_at: datetime, metadata: dict[str, Any]) -> PlaceToolResponse:
        return self._response(
            status=PlaceToolStatus.CREDENTIALS_BLOCKED,
            request=request,
            retrieved_at=retrieved_at,
            metadata={**metadata, "error_code": "missing_goong_api_key"},
            error=PlaceToolError(code="missing_goong_api_key", message="Goong Places credentials are not configured.", retryable=False),
        )

    def _safe_error(self, request: Any, retrieved_at: datetime, metadata: dict[str, Any], code: str, message: str, retryable: bool) -> PlaceToolResponse:
        return self._response(
            status=PlaceToolStatus.UPSTREAM_ERROR,
            request=request,
            retrieved_at=retrieved_at,
            metadata={**metadata, "error_code": code},
            error=PlaceToolError(code=code, message=message, retryable=retryable),
        )

    def _response(
        self,
        *,
        status: PlaceToolStatus,
        request: Any,
        retrieved_at: datetime,
        metadata: dict[str, Any],
        candidates: list[PlaceCandidate] | None = None,
        error: PlaceToolError | None = None,
    ) -> PlaceToolResponse:
        return PlaceToolResponse(
            status=status,
            source=PlaceToolSource.GOONG_PLACES,
            request=request,
            retrieved_at=retrieved_at,
            candidates=candidates or [],
            error=error,
            metadata=metadata,
        )


def normalize_place(place: Mapping[str, Any], *, origin: LatLng | None = None) -> PlaceCandidate | None:
    """Normalize one Goong place object without leaking raw provider payloads."""

    place_id = _string(place.get("place_id")) or _string(place.get("id")) or _resource_id(place.get("name"))
    display_name = _display_name(place.get("displayName")) or _string(place.get("name")) or _string(place.get("description")) or place_id
    if not place_id or not display_name:
        return None

    location = _location(place.get("location")) or _geometry_location(place.get("geometry"))
    distance_meters = _int(place.get("distance_meters")) or _int(place.get("distanceMeters"))
    if distance_meters is None and origin and location:
        distance_meters = _haversine_meters(origin, location)

    types = [item for item in place.get("types", []) if isinstance(item, str)] if isinstance(place.get("types"), list) else []
    accessibility = place.get("accessibilityOptions") if isinstance(place.get("accessibilityOptions"), Mapping) else {}
    accessibility_tags = [key for key, value in accessibility.items() if value is True]

    return PlaceCandidate(
        place_id=place_id,
        resource_name=_string(place.get("reference")) or _resource_id(place.get("name")),
        display_name=display_name,
        types=types,
        primary_type=_string(place.get("primaryType")) or (types[0] if types else None),
        formatted_address=_string(place.get("formatted_address")) or _string(place.get("formattedAddress")) or _string(place.get("description")),
        short_formatted_address=_string(place.get("short_formatted_address")) or _string(place.get("compound", {}).get("district") if isinstance(place.get("compound"), Mapping) else None),
        location=location,
        rating=_float(place.get("rating")),
        user_rating_count=_int(place.get("user_ratings_total")) or _int(place.get("userRatingCount")),
        price_level=_price_level(place.get("price_level")) or _price_level(place.get("priceLevel")),
        open_now=_open_now(place),
        business_status=_string(place.get("business_status")) or _string(place.get("businessStatus")),
        accessibility_options=dict(accessibility),
        national_phone_number=_string(place.get("formatted_phone_number")) or _string(place.get("nationalPhoneNumber")),
        international_phone_number=_string(place.get("international_phone_number")) or _string(place.get("internationalPhoneNumber")),
        map_uri=_string(place.get("url")) or _string(place.get("googleMapsUri")),
        website_uri=_string(place.get("website")) or _string(place.get("websiteUri")),
        fairness_tags=accessibility_tags or ["accessibility_unknown"],
        route_context=RouteContext(origin=origin, distance_meters=distance_meters) if distance_meters is not None else None,
    )


def _extract_result_list(payload: Mapping[str, Any]) -> list[Any] | None:
    for key in ("results", "predictions", "places"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return None


def _extract_detail_object(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for key in ("result", "place"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
    return payload if "place_id" in payload or "geometry" in payload else None


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
    lat = value.get("lat", value.get("latitude"))
    lng = value.get("lng", value.get("longitude"))
    if lat is None or lng is None:
        return None
    return LatLng(lat=float(lat), lng=float(lng))


def _geometry_location(value: Any) -> LatLng | None:
    if not isinstance(value, Mapping):
        return None
    return _location(value.get("location"))


def _open_now(place: Mapping[str, Any]) -> bool | None:
    opening_hours = place.get("opening_hours") or place.get("currentOpeningHours")
    if isinstance(opening_hours, Mapping):
        if isinstance(opening_hours.get("open_now"), bool):
            return opening_hours["open_now"]
        if isinstance(opening_hours.get("openNow"), bool):
            return opening_hours["openNow"]
    return None


def _price_level(value: Any) -> int | None:
    if isinstance(value, int):
        return value if 0 <= value <= 4 else None
    if isinstance(value, str) and value.isdigit():
        parsed = int(value)
        return parsed if 0 <= parsed <= 4 else None
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


def _location_param(location: LatLng) -> str:
    return f"{location.lat},{location.lng}"


def _haversine_meters(origin: LatLng, destination: LatLng) -> int:
    radius_m = 6_371_000
    lat1 = math.radians(origin.lat)
    lat2 = math.radians(destination.lat)
    delta_lat = math.radians(destination.lat - origin.lat)
    delta_lng = math.radians(destination.lng - origin.lng)
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    return round(radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


