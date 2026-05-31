"""Google Places API (New) client seam and safe normalization service.

Uses Google Places API (New) endpoints:
- Text Search: POST /v1/places:searchText
- Nearby Search: POST /v1/places:searchNearby
- Place Details: GET /v1/places/{place_id}

All endpoints require X-Goog-Api-Key and X-Goog-FieldMask headers.
Configured via GOOGLE_PLACES_API_KEY in .env.

Circuit breaker: opens after consecutive failures, probes after cooldown,
returns cached results on open/timeout/error states.

Cache integration: successful OK results are upserted to Postgres cache;
on provider failure/circuit-open, cache lookup is attempted before returning
an honest unavailable status.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
import structlog

from app.core.config import Settings, get_settings
from app.models.places import (
    DEFAULT_SEARCH_RADIUS_METERS,
    GOOGLE_PLACES_FIELD_MASK,
    HAM_NINH_CENTER,
    PlaceCandidate,
    PlaceDetailsRequest,
    PlaceNearbyRequest,
    PlaceRecommendationStatus,
    PlaceSearchRequest,
    PlaceToolError,
    PlaceToolResponse,
    PlaceToolSource,
    PlaceToolStatus,
    ProviderStatus,
    RouteContext,
    SearchPlacesToolResult,
)
from app.models.request import LatLng

logger = structlog.get_logger(__name__)

PLACES_BASE_URL = "https://places.googleapis.com"
TEXT_SEARCH_PATH = "/v1/places:searchText"
NEARBY_SEARCH_PATH = "/v1/places:searchNearby"
DETAILS_PATH = "/v1/places"

# Field mask covering all fields consumed by normalize_place().
# Google Places API (New) requires explicit field masks for billing.
_DEFAULT_FIELD_MASK = GOOGLE_PLACES_FIELD_MASK

_GOOGLE_AUTH_CODES = {"REQUEST_DENIED", "PERMISSION_DENIED"}
_GOOGLE_RATE_LIMIT_CODES = {"RESOURCE_EXHAUSTED"}


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitState:
    """Simple circuit breaker with open/half-open/closed states.

    - closed: normal operation, consecutive failures are counted
    - open: provider calls are skipped; cache is used instead
    - half-open: one probe call is allowed through after cooldown

    State is in-memory only — resets on process restart.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._consecutive_failures = 0
        self._state: str = "closed"
        self._opened_at: datetime | None = None

    @property
    def state(self) -> str:
        """Current circuit state: 'closed', 'open', or 'half-open'."""
        if self._state == "open" and self._opened_at is not None:
            elapsed = (datetime.now(UTC) - self._opened_at).total_seconds()
            if elapsed >= self._cooldown_seconds:
                self._state = "half-open"
                logger.info("circuit.half_open", reason="cooldown_elapsed")
        return self._state

    @property
    def is_open(self) -> bool:
        return self.state in ("open", "half-open")

    def record_success(self) -> None:
        """Record a successful provider call — reset failure count and close circuit."""
        self._consecutive_failures = 0
        if self._state == "half-open":
            logger.info("circuit.closed", reason="probe_succeeded")
        self._state = "closed"
        self._opened_at = None

    def record_failure(self) -> None:
        """Record a provider failure — advance failure count, open if threshold exceeded."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold and self._state == "closed":
            self._state = "open"
            self._opened_at = datetime.now(UTC)
            logger.warning(
                "circuit.opened",
                consecutive_failures=self._consecutive_failures,
                threshold=self._failure_threshold,
            )

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures


# ---------------------------------------------------------------------------
# HTTP Client Protocol
# ---------------------------------------------------------------------------

class PlacesHttpClient(Protocol):
    """Minimal async HTTP seam so tests and agents can substitute a mock client."""

    async def post(self, path: str, *, json: dict[str, Any], headers: dict[str, str]) -> Any: ...

    async def get(self, path: str, *, headers: dict[str, str]) -> Any: ...


class HttpxPlacesClient:
    """Thin httpx-backed client for Google Places REST endpoints."""

    def __init__(self, *, base_url: str = PLACES_BASE_URL, timeout: float = 8.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def post(self, path: str, *, json: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        return await self._client.post(path, json=json, headers=headers)

    async def get(self, path: str, *, headers: dict[str, str]) -> httpx.Response:
        return await self._client.get(path, headers=headers)

    async def aclose(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class GooglePlacesService:
    """Server-side Google Places (New) service returning normalized candidates and safe envelopes.

    Integrates:
    - Circuit breaker (in-memory) to avoid repeated calls during outages
    - Postgres place cache for fallback on provider failure/circuit-open
    - Cache upsert on successful OK responses
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: PlacesHttpClient | None = None,
        place_cache: Any | None = None,
        circuit: CircuitState | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or HttpxPlacesClient()
        self._place_cache = place_cache  # PlaceCacheProtocol | None
        self._circuit = circuit or CircuitState()

    def _api_key(self) -> str | None:
        key = self._settings.GOOGLE_PLACES_API_KEY.strip()
        return key if key else None

    def _auth_headers(self, language_code: str = "en") -> dict[str, str]:
        headers = {
            "X-Goog-Api-Key": self._api_key() or "",
            "X-Goog-FieldMask": _DEFAULT_FIELD_MASK,
            "Content-Type": "application/json",
        }
        if language_code:
            headers["X-Goog-Language"] = language_code
        return headers

    # -- text Search (POST /v1/places:searchText) -------------------

    async def text_search(self, request: PlaceSearchRequest) -> SearchPlacesToolResult:
        body: dict[str, Any] = {
            "textQuery": request.query,
            "maxResultCount": request.max_result_count,
        }
        # Optional location bias
        if request.location_bias:
            body["locationBias"] = {
                "circle": {
                    "center": {
                        "latitude": request.location_bias.lat,
                        "longitude": request.location_bias.lng,
                    },
                    "radius": request.radius_meters,
                }
            }
        if request.included_type:
            body["includedType"] = request.included_type

        return await self._execute_search(
            operation="text_search",
            path=TEXT_SEARCH_PATH,
            body=body,
            request=request,
            origin=request.location_bias,
            metadata={"endpoint": "google_text_search", "radius_meters": request.radius_meters},
        )

    # -- Nearby Search (POST /v1/places:searchNearby) ---------------

    async def nearby_search(self, request: PlaceNearbyRequest) -> SearchPlacesToolResult:
        body: dict[str, Any] = {
            "maxResultCount": request.max_result_count,
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": request.center.lat,
                        "longitude": request.center.lng,
                    },
                    "radius": request.radius_meters,
                }
            },
        }
        if request.included_type:
            body["includedTypes"] = [request.included_type]

        return await self._execute_search(
            operation="nearby_search",
            path=NEARBY_SEARCH_PATH,
            body=body,
            request=request,
            origin=request.center,
            metadata={
                "endpoint": "google_nearby_search",
                "center": f"{request.center.lat},{request.center.lng}",
                "radius_meters": request.radius_meters,
                "included_type": request.included_type,
            },
        )

    # -- Place Details (GET /v1/places/{place_id}) ------------------

    async def details(self, request: PlaceDetailsRequest) -> SearchPlacesToolResult:
        retrieved_at = datetime.now(UTC)
        metadata = {"endpoint": "google_detail"}
        api_key = self._api_key()
        if not api_key:
            return self._credential_error(request, retrieved_at, metadata)

        place_id = request.place_id.removeprefix("places/")
        path = f"{DETAILS_PATH}/{place_id}"
        headers = self._auth_headers(request.language_code)

        return await self._execute_details(
            operation="details",
            path=path,
            headers=headers,
            request=request,
            retrieved_at=retrieved_at,
            metadata=metadata,
        )

    # -- Internal: search execution ---------------------------------

    async def _execute_search(
        self,
        *,
        operation: str,
        path: str,
        body: dict[str, Any],
        request: PlaceSearchRequest | PlaceNearbyRequest,
        origin: LatLng,
        metadata: dict[str, Any],
    ) -> SearchPlacesToolResult:
        retrieved_at = datetime.now(UTC)
        api_key = self._api_key()
        if not api_key:
            return self._credential_error(request, retrieved_at, metadata)

        # Check circuit breaker before making outbound call
        # half-open allows one probe through; only skip if fully open
        if self._circuit.state == "open":
            logger.info("circuit.open_skip", operation=operation)
            return await self._fallback_from_cache(
                request=request,
                retrieved_at=retrieved_at,
                metadata={**metadata, "circuit_state": self._circuit.state},
                reason="circuit_open",
            )

        language_code = getattr(request, "language_code", "en")
        headers = self._auth_headers(language_code)

        response_payload = await self._request_post(operation, path, body, headers, request, retrieved_at, metadata)
        if isinstance(response_payload, SearchPlacesToolResult):
            # Provider returned an error — record failure, try cache fallback
            self._circuit.record_failure()
            return await self._fallback_from_cache(
                request=request,
                retrieved_at=retrieved_at,
                metadata={**metadata, "provider_error": response_payload.status.value},
                reason=f"provider_{response_payload.status.value}",
                provider_result=response_payload,
            )

        # Provider returned a raw payload — success path
        self._circuit.record_success()

        raw_results = _extract_places_list(response_payload)
        if raw_results is None:
            self._circuit.record_failure()
            return self._safe_error(request, retrieved_at, metadata, "malformed_response", "Google Places returned an unexpected response shape.", True)

        candidates: list[PlaceCandidate] = []
        for raw_place in raw_results[: request.max_result_count]:
            if not isinstance(raw_place, dict):
                continue
            candidate = normalize_place(raw_place, origin=origin)
            if candidate:
                candidates.append(candidate)

        # Upsert successful results to cache (fire-and-forget — do not block response)
        if candidates:
            await self._try_cache_upsert(request, candidates)

        if not candidates:
            return self._response(status=PlaceToolStatus.EMPTY, request=request, retrieved_at=retrieved_at, metadata={**metadata, "error_code": "no_results"})
        return self._response(status=PlaceToolStatus.OK, request=request, retrieved_at=retrieved_at, metadata=metadata, candidates=candidates)

    # -- Internal: details execution --------------------------------

    async def _execute_details(
        self,
        *,
        operation: str,
        path: str,
        headers: dict[str, str],
        request: PlaceDetailsRequest,
        retrieved_at: datetime,
        metadata: dict[str, Any],
    ) -> SearchPlacesToolResult:
        # Check circuit breaker — half-open allows one probe through
        if self._circuit.state == "open":
            logger.info("circuit.open_skip", operation=operation)
            return await self._fallback_from_cache(
                request=request,
                retrieved_at=retrieved_at,
                metadata={**metadata, "circuit_state": self._circuit.state},
                reason="circuit_open",
            )

        response_payload = await self._request_get(operation, path, headers, request, retrieved_at, metadata)
        if isinstance(response_payload, SearchPlacesToolResult):
            # Provider returned an error — record failure, try cache fallback
            self._circuit.record_failure()
            return await self._fallback_from_cache(
                request=request,
                retrieved_at=retrieved_at,
                metadata={**metadata, "provider_error": response_payload.status.value},
                reason=f"provider_{response_payload.status.value}",
                provider_result=response_payload,
            )

        # Provider returned a raw payload — success path
        self._circuit.record_success()

        # Google Details returns the place object directly (not wrapped in "result")
        raw_place = response_payload if isinstance(response_payload, dict) and "id" in response_payload else None
        if raw_place is None:
            self._circuit.record_failure()
            return self._safe_error(request, retrieved_at, metadata, "malformed_response", "Google Places returned an unexpected response shape.", True)

        candidate = normalize_place(raw_place)
        if not candidate:
            return self._response(status=PlaceToolStatus.EMPTY, request=request, retrieved_at=retrieved_at, metadata={**metadata, "error_code": "no_results"})

        # Upsert successful result to cache
        await self._try_cache_upsert(request, [candidate])

        return self._response(status=PlaceToolStatus.OK, request=request, retrieved_at=retrieved_at, metadata=metadata, candidates=[candidate])

    # -- HTTP request wrappers --------------------------------------

    async def _request_post(
        self,
        operation: str,
        path: str,
        body: dict[str, Any],
        headers: dict[str, str],
        request: Any,
        retrieved_at: datetime,
        metadata: dict[str, Any],
    ) -> dict[str, Any] | SearchPlacesToolResult:
        try:
            response = await self._client.post(path, json=body, headers=headers)
        except httpx.TimeoutException:
            logger.warning("google_places_timeout", extra={"operation": operation})
            return self._safe_error(request, retrieved_at, metadata, "timeout", "Google Places request timed out.", True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("google_places_client_error", extra={"operation": operation, "error_type": type(exc).__name__})
            return self._safe_error(request, retrieved_at, metadata, "upstream_error", "Google Places request failed.", True)

        return self._handle_response(response, operation, request, retrieved_at, metadata)

    async def _request_get(
        self,
        operation: str,
        path: str,
        headers: dict[str, str],
        request: Any,
        retrieved_at: datetime,
        metadata: dict[str, Any],
    ) -> dict[str, Any] | SearchPlacesToolResult:
        try:
            response = await self._client.get(path, headers=headers)
        except httpx.TimeoutException:
            logger.warning("google_places_timeout", extra={"operation": operation})
            return self._safe_error(request, retrieved_at, metadata, "timeout", "Google Places request timed out.", True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("google_places_client_error", extra={"operation": operation, "error_type": type(exc).__name__})
            return self._safe_error(request, retrieved_at, metadata, "upstream_error", "Google Places request failed.", True)

        return self._handle_response(response, operation, request, retrieved_at, metadata)

    def _handle_response(
        self,
        response: Any,
        operation: str,
        request: Any,
        retrieved_at: datetime,
        metadata: dict[str, Any],
    ) -> dict[str, Any] | SearchPlacesToolResult:
        status_code = getattr(response, "status_code", 200)

        if status_code in (401, 403):
            return self._safe_error(request, retrieved_at, metadata, "auth_error", "Google Places rejected the configured credentials.", False)
        if status_code == 429:
            return self._safe_error(request, retrieved_at, metadata, "quota_exceeded", "Google Places quota was exceeded or rate limited.", True)
        if status_code >= 500:
            logger.warning("google_places_upstream_5xx", extra={"operation": operation, "status_code": status_code})
            return self._safe_error(request, retrieved_at, metadata, "upstream_error", "Google Places returned an upstream error.", True)
        if status_code >= 400:
            return self._safe_error(request, retrieved_at, metadata, "upstream_error", "Google Places request was not accepted.", False)

        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            logger.warning("google_places_malformed_json", extra={"operation": operation})
            return self._safe_error(request, retrieved_at, metadata, "malformed_response", "Google Places returned malformed data.", True)

        if not isinstance(payload, dict):
            return self._safe_error(request, retrieved_at, metadata, "malformed_response", "Google Places returned an unexpected response shape.", True)

        # Check for Google error envelope
        error = payload.get("error")
        if isinstance(error, dict):
            error_status = error.get("status", "")
            error_message = error.get("message", "")
            if error_status in _GOOGLE_AUTH_CODES:
                return self._safe_error(request, retrieved_at, metadata, "auth_error", f"Google Places rejected the request: {error_message}", False)
            if error_status in _GOOGLE_RATE_LIMIT_CODES:
                return self._safe_error(request, retrieved_at, metadata, "quota_exceeded", f"Google Places quota exceeded: {error_message}", True)
            return self._safe_error(request, retrieved_at, metadata, "upstream_error", f"Google Places error: {error_message}", True)

        return payload

    # -- Cache fallback ---------------------------------------------

    async def _fallback_from_cache(
        self,
        *,
        request: PlaceSearchRequest | PlaceDetailsRequest,
        retrieved_at: datetime,
        metadata: dict[str, Any],
        reason: str,
        provider_result: SearchPlacesToolResult | None = None,
    ) -> SearchPlacesToolResult:
        """Try the Postgres cache before returning an honest unavailable response.

        No RAG fallback or document citations are introduced here.
        """
        # Only text/nearby searches use PlaceSearchRequest which the cache supports
        if self._place_cache is None or not isinstance(request, PlaceSearchRequest):
            return self._unavailable_response(
                request=request,
                retrieved_at=retrieved_at,
                metadata=metadata,
                reason=reason,
                warning="place cache not configured",
            )

        try:
            candidates, diagnostics = await self._place_cache.lookup(request)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache_fallback_error", error_type=type(exc).__name__)
            return self._unavailable_response(
                request=request,
                retrieved_at=retrieved_at,
                metadata=metadata,
                reason=reason,
                warning=f"cache lookup failed: {type(exc).__name__}",
            )

        if diagnostics.cache_hit and candidates:
            logger.info(
                "cache_fallback_hit",
                cache_key=diagnostics.get("cache_key", "unknown")[:8],
                candidate_count=len(candidates),
            )
            return self._response(
                status=PlaceToolStatus.OK,
                request=request,
                retrieved_at=retrieved_at,
                metadata={**metadata, "fallback_source": "cache"},
                candidates=candidates,
            )

        # Cache miss or stale — return honest unavailable
        cache_status = diagnostics.result if diagnostics else "no_cache"
        # Extract specific error type from metadata if available
        specific_reason = reason
        provider_error_code = metadata.get("provider_error")
        if provider_error_code:
            specific_reason = f"{reason} (provider error: {provider_error_code})"

        return self._unavailable_response(
            request=request,
            retrieved_at=retrieved_at,
            metadata={**metadata, "cache_result": cache_status},
            reason=specific_reason,
            warning=f"cache {cache_status}",
        )

    async def _try_cache_upsert(
        self,
        request: PlaceSearchRequest | PlaceNearbyRequest,
        candidates: list[PlaceCandidate],
    ) -> None:
        """Fire-and-forget cache upsert for successful results."""
        if self._place_cache is None or not isinstance(request, PlaceSearchRequest):
            return
        try:
            diag = await self._place_cache.upsert(request, candidates)
            if diag.result == "write_ok":
                logger.info("cache_upsert_ok", cache_key=diag.get("cache_key", "unknown")[:8])
            else:
                logger.warning("cache_upsert_failed", reason=diag.get("reason", "unknown"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache_upsert_error", error_type=type(exc).__name__)

    # -- Response helpers -------------------------------------------

    def _credential_error(self, request: Any, retrieved_at: datetime, metadata: dict[str, Any]) -> SearchPlacesToolResult:
        return self._response(
            status=PlaceToolStatus.CREDENTIALS_BLOCKED,
            request=request,
            retrieved_at=retrieved_at,
            metadata={**metadata, "error_code": "missing_google_api_key"},
            error=PlaceToolError(code="missing_google_api_key", message="Google Places credentials are not configured.", retryable=False),
        )

    def _safe_error(self, request: Any, retrieved_at: datetime, metadata: dict[str, Any], code: str, message: str, retryable: bool) -> SearchPlacesToolResult:
        return self._response(
            status=PlaceToolStatus.UPSTREAM_ERROR,
            request=request,
            retrieved_at=retrieved_at,
            metadata={**metadata, "error_code": code},
            error=PlaceToolError(code=code, message=message, retryable=retryable),
        )

    def _unavailable_response(
        self,
        *,
        request: Any,
        retrieved_at: datetime,
        metadata: dict[str, Any],
        reason: str,
        warning: str | None = None,
    ) -> SearchPlacesToolResult:
        """Return an honest unavailable response with no RAG fallback or citations."""
        warnings: list[str] = []
        reasoning_log: list[str] = [f"provider unavailable: {reason}"]
        if warning:
            warnings.append(warning)
            reasoning_log.append(warning)

        return SearchPlacesToolResult(
            status=PlaceToolStatus.UNAVAILABLE,
            source=PlaceToolSource.GOOGLE_PLACES,
            provider_status=ProviderStatus(),
            candidates=[],
            warnings=warnings,
            reasoning_log=reasoning_log,
            explanation=None,
            place_recommendation_status=PlaceRecommendationStatus(
                provider_places_returned=0,
                candidates_after_normalization=0,
                filters_applied=[],
                reason=reason,
            ),
            audit={
                "endpoint": metadata.get("endpoint", "unknown"),
                "field_mask": GOOGLE_PLACES_FIELD_MASK,
                "fallback_reason": reason,
            },
            retrieved_at=retrieved_at,
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
    ) -> SearchPlacesToolResult:
        reasoning_log: list[str] = []
        warnings: list[str] = []
        if error:
            reasoning_log.append(f"error: {error.code} — {error.message}")
        if status == PlaceToolStatus.EMPTY:
            reasoning_log.append("provider returned zero usable places")
        elif status == PlaceToolStatus.CREDENTIALS_BLOCKED:
            reasoning_log.append("credentials not configured — no outbound request made")
        elif status == PlaceToolStatus.OK and candidates:
            reasoning_log.append(f"normalized {len(candidates)} candidate(s) from provider response")
        if metadata.get("fallback_source") == "cache":
            reasoning_log.append("results served from durable cache after provider failure")
            warnings.append("provider unavailable; showing cached results")

        return SearchPlacesToolResult(
            status=status,
            source=PlaceToolSource.CACHE if metadata.get("fallback_source") == "cache" else PlaceToolSource.GOOGLE_PLACES,
            provider_status=ProviderStatus(),
            candidates=candidates or [],
            warnings=warnings,
            reasoning_log=reasoning_log,
            explanation=None,
            place_recommendation_status=PlaceRecommendationStatus(
                provider_places_returned=len(candidates) if candidates else 0,
                candidates_after_normalization=len(candidates) if candidates else 0,
                filters_applied=[f"max_result_count={getattr(request, 'max_result_count', 'N/A')}"],
                reason="ok" if status == PlaceToolStatus.OK else str(status),
            ),
            audit={
                "endpoint": metadata.get("endpoint", "unknown"),
                "field_mask": GOOGLE_PLACES_FIELD_MASK,
            },
            retrieved_at=retrieved_at,
        )


def normalize_place(place: dict[str, Any], *, origin: LatLng | None = None) -> PlaceCandidate | None:
    """Normalize one Google Places (New) place object without leaking raw provider payloads.

    Google Places (New) response fields:
    - places[].id, displayName.text, types[], primaryType
    - formattedAddress, shortFormattedAddress, location{lat,lng}
    - rating, userRatingCount, priceLevel (enum string)
    - currentOpeningHours.openNow, businessStatus
    - accessibilityOptions{}, nationalPhoneNumber, internationalPhoneNumber
    - googleMapsUri, websiteUri
    """

    place_id = _string(place.get("id"))
    if not place_id:
        return None

    display_name = _display_name(place.get("displayName")) or place_id

    location = _location(place.get("location"))
    distance_meters: int | None = None
    if origin and location:
        distance_meters = _haversine_meters(origin, location)

    types = [item for item in place.get("types", []) if isinstance(item, str)] if isinstance(place.get("types"), list) else []
    accessibility = place.get("accessibilityOptions") if isinstance(place.get("accessibilityOptions"), dict) else {}
    accessibility_tags = [key for key, value in accessibility.items() if value is True]

    return PlaceCandidate(
        place_id=place_id,
        resource_name=f"places/{place_id}",
        display_name=display_name,
        types=types,
        primary_type=_string(place.get("primaryType")) or (types[0] if types else None),
        formatted_address=_string(place.get("formattedAddress")),
        short_formatted_address=_string(place.get("shortFormattedAddress")),
        location=location,
        rating=_float(place.get("rating")),
        user_rating_count=_int(place.get("userRatingCount")),
        price_level=_price_level_google(place.get("priceLevel")),
        open_now=_open_now_google(place),
        business_status=_string(place.get("businessStatus")),
        accessibility_options=dict(accessibility),
        national_phone_number=_string(place.get("nationalPhoneNumber")),
        international_phone_number=_string(place.get("internationalPhoneNumber")),
        map_uri=_string(place.get("googleMapsUri")),
        website_uri=_string(place.get("websiteUri")),
        fairness_tags=accessibility_tags or ["accessibility_unknown"],
        route_context=RouteContext(origin=origin, distance_meters=distance_meters) if distance_meters is not None else None,
    )


def _extract_places_list(payload: dict[str, Any]) -> list[Any] | None:
    """Extract the places array from Google Places API (New) response."""
    places = payload.get("places")
    if isinstance(places, list):
        return places
    return None


def _display_name(value: Any) -> str | None:
    """Extract display name text from LocalizedText object or plain string."""
    if isinstance(value, dict):
        return _string(value.get("text"))
    return _string(value)


def _location(value: Any) -> LatLng | None:
    """Extract lat/lng from Google location object."""
    if not isinstance(value, dict):
        return None
    lat = value.get("lat")
    lng = value.get("lng")
    if lat is None or lng is None:
        return None
    return LatLng(lat=float(lat), lng=float(lng))


def _open_now_google(place: dict[str, Any]) -> bool | None:
    """Extract openNow from currentOpeningHours (Google Places New format)."""
    opening_hours = place.get("currentOpeningHours") or place.get("regularOpeningHours")
    if isinstance(opening_hours, dict):
        open_now = opening_hours.get("openNow")
        if isinstance(open_now, bool):
            return open_now
    return None


def _price_level_google(value: Any) -> int | None:
    """Convert Google priceLevel enum string to int [0-4].

    Google values: "PRICE_LEVEL_FREE", "PRICE_LEVEL_INEXPENSIVE",
    "PRICE_LEVEL_MODERATE", "PRICE_LEVEL_EXPENSIVE", "PRICE_LEVEL_VERY_EXPENSIVE"
    """
    if isinstance(value, int):
        return value if 0 <= value <= 4 else None
    if isinstance(value, str):
        mapping = {
            "PRICE_LEVEL_FREE": 0,
            "PRICE_LEVEL_INEXPENSIVE": 1,
            "PRICE_LEVEL_MODERATE": 2,
            "PRICE_LEVEL_EXPENSIVE": 3,
            "PRICE_LEVEL_VERY_EXPENSIVE": 4,
        }
        return mapping.get(value.upper())
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
    """Calculate great-circle distance in metres between two lat/lng points."""
    radius_m = 6_371_000
    lat1 = math.radians(origin.lat)
    lat2 = math.radians(destination.lat)
    delta_lat = math.radians(destination.lat - origin.lat)
    delta_lng = math.radians(destination.lng - origin.lng)
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    return round(radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))
