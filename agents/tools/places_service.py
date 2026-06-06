"""Google-first Places API service with Goong fallback.

Google Places API (New) primary provider:
- Text Search: POST /v1/places:searchText with X-Goog-Api-Key and X-Goog-FieldMask
- Nearby Search: POST /v1/places:searchNearby
- Place Details: GET /v1/places/{place_id}

Goong Places fallback provider (when Google credentials unavailable or failing):
- Text Search: GET /place/search with api_key query param
- Nearby Search: GET /place/nearby with api_key query param
- Place Details: GET /place/detail with api_key query param

DualPlacesService composition: Google-first with Goong fallback.
When GOOGLE_PLACES_API_KEY is present, Google is attempted first.
On Google failure (missing creds, auth rejected, quota, timeout, malformed, upstream error),
Goong is called if GOONG_API_KEY is configured, with metadata tracking
primary_source, fallback_source, fallback_reason, and credential status.

Configured via GOOGLE_PLACES_API_KEY and GOONG_API_KEY in .env.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx
import structlog

from app.core.config import Settings, get_settings
from app.models.places import (
    DEFAULT_SEARCH_RADIUS_METERS,
    GOOGLE_PLACE_DETAILS_FIELD_MASK,
    GOOGLE_PLACES_FIELD_MASK,
    GOOGLE_PLACES_PROVIDER_CONTRACT_VERSION,
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

    async def get(self, path: str, *, headers: dict[str, str], params: dict[str, Any] | None = None) -> Any: ...


class HttpxPlacesClient:
    """Thin httpx-backed client for Google/Goong Places REST endpoints."""

    def __init__(self, *, base_url: str = PLACES_BASE_URL, timeout: float = 8.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def post(self, path: str, *, json: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        return await self._client.post(path, json=json, headers=headers)

    async def get(self, path: str, *, headers: dict[str, str], params: dict[str, Any] | None = None) -> httpx.Response:
        return await self._client.get(path, headers=headers, params=params)

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

    def _auth_headers(self, language_code: str = "en", field_mask: str = _DEFAULT_FIELD_MASK) -> dict[str, str]:
        headers = {
            "X-Goog-Api-Key": self._api_key() or "",
            "X-Goog-FieldMask": field_mask,
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
            metadata={"endpoint": "google_text_search", "field_mask": GOOGLE_PLACES_FIELD_MASK, "radius_meters": request.radius_meters},
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
                "field_mask": GOOGLE_PLACES_FIELD_MASK,
                "center": f"{request.center.lat},{request.center.lng}",
                "radius_meters": request.radius_meters,
                "included_type": request.included_type,
            },
        )

    # -- Place Details (GET /v1/places/{place_id}) ------------------

    async def details(self, request: PlaceDetailsRequest) -> SearchPlacesToolResult:
        retrieved_at = datetime.now(UTC)
        metadata = {"endpoint": "google_detail", "field_mask": GOOGLE_PLACE_DETAILS_FIELD_MASK}
        api_key = self._api_key()
        if not api_key:
            return self._credential_error(request, retrieved_at, metadata)

        place_id = request.place_id.removeprefix("places/")
        path = f"{DETAILS_PATH}/{place_id}"
        headers = self._auth_headers(request.language_code, GOOGLE_PLACE_DETAILS_FIELD_MASK)

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

        if candidates:
            candidates, hydrated_count = await self._hydrate_search_candidates(
                candidates, language_code=language_code, origin=origin
            )
            if hydrated_count:
                metadata = {**metadata, "details_hydrated": hydrated_count}

        # Upsert successful results to cache (fire-and-forget — do not block response)
        if candidates:
            await self._try_cache_upsert(request, candidates)

        if not candidates:
            return self._response(status=PlaceToolStatus.EMPTY, request=request, retrieved_at=retrieved_at, metadata={**metadata, "error_code": "no_results"})
        return self._response(status=PlaceToolStatus.OK, request=request, retrieved_at=retrieved_at, metadata=metadata, candidates=candidates)

    async def _hydrate_search_candidates(
        self,
        candidates: list[PlaceCandidate],
        *,
        language_code: str,
        origin: LatLng | None,
        limit: int = 5,
    ) -> tuple[list[PlaceCandidate], int]:
        """Hydrate top search candidates with Place Details (New) rich fields.

        Search stays lightweight; details are fetched only for the top few
        candidates. Failures are ignored so provider details cannot break a
        successful search result.
        """
        hydrated: list[PlaceCandidate] = []
        hydrated_count = 0
        for index, candidate in enumerate(candidates):
            if index >= limit:
                hydrated.append(candidate)
                continue
            try:
                result = await self.details(
                    PlaceDetailsRequest(place_id=candidate.place_id, language_code=language_code)
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("google_place_details_hydrate_error", place_id=candidate.place_id, error_type=type(exc).__name__)
                hydrated.append(candidate)
                continue
            if result.status == PlaceToolStatus.OK and result.candidates:
                rich = result.candidates[0]
                if origin and rich.location and rich.route_context is None:
                    rich = rich.model_copy(update={
                        "route_context": RouteContext(origin=origin, distance_meters=_haversine_meters(origin, rich.location))
                    })
                hydrated.append(_merge_place_candidate(candidate, rich))
                hydrated_count += 1
            else:
                hydrated.append(candidate)
        return hydrated, hydrated_count

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
        Stale cache entries are served as degraded results with a staleness warning.
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

        cache_status = diagnostics.result if diagnostics else "no_cache"

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

        # Stale cache — serve as degraded results with staleness warning
        if diagnostics.cache_stale and candidates:
            staleness = diagnostics.get("staleness_seconds", "unknown")
            logger.info(
                "cache_fallback_stale",
                cache_key=diagnostics.get("cache_key", "unknown")[:8],
                candidate_count=len(candidates),
                staleness_seconds=staleness,
            )
            return self._response(
                status=PlaceToolStatus.OK,
                request=request,
                retrieved_at=retrieved_at,
                metadata={
                    **metadata,
                    "fallback_source": "cache_stale",
                    "staleness_seconds": staleness,
                },
                candidates=candidates,
            )

        # Cache miss or stale with no data — return honest unavailable
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

        audit: dict[str, Any] = {
                "endpoint": metadata.get("endpoint", "unknown"),
                "field_mask": metadata.get("field_mask", GOOGLE_PLACES_FIELD_MASK),
                "fallback_reason": reason,
            }
        if "cache_result" in metadata:
            audit["cache_result"] = metadata["cache_result"]
        if "circuit_state" in metadata:
            audit["circuit_state"] = metadata["circuit_state"]
        if "details_hydrated" in metadata:
            audit["details_hydrated"] = metadata["details_hydrated"]

        # Build enriched request_metadata with full diagnostic keys
        request_metadata: dict[str, Any] = {
            "endpoint": metadata.get("endpoint", "unknown"),
            "field_mask": metadata.get("field_mask", GOOGLE_PLACES_FIELD_MASK),
            "credential_status": "live",  # key was present but provider failed
            "provider_attempted": PlaceToolSource.GOOGLE_PLACES.value,
            "fallback_reason": reason,
            "result_count": 0,
            "provider_contract_version": GOOGLE_PLACES_PROVIDER_CONTRACT_VERSION,
            "language_code": getattr(request, "language_code", None),
            "max_result_count": getattr(request, "max_result_count", None),
        }
        if metadata.get("fallback_source"):
            request_metadata["fallback_source"] = metadata["fallback_source"]

        return SearchPlacesToolResult(
            status=PlaceToolStatus.UNAVAILABLE,
            source=PlaceToolSource.GOOGLE_PLACES,
            provider_status=ProviderStatus(),
            interpreted_query=getattr(request, "query", None),
            request_metadata=request_metadata,
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
            audit=audit,
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
        fallback_source = metadata.get("fallback_source")
        if error:
            reasoning_log.append(f"error: {error.code} — {error.message}")
        if status == PlaceToolStatus.EMPTY:
            reasoning_log.append("provider returned zero usable places")
        elif status == PlaceToolStatus.CREDENTIALS_BLOCKED:
            reasoning_log.append("credentials not configured — no outbound request made")
        elif status == PlaceToolStatus.OK and candidates:
            if fallback_source == "cache_stale":
                staleness = metadata.get("staleness_seconds", "unknown")
                reasoning_log.append(f"served {len(candidates)} candidate(s) from stale cache ({staleness}s old)")
                warnings.append("provider unavailable; showing stale cached results")
            elif fallback_source == "cache":
                reasoning_log.append(f"served {len(candidates)} candidate(s) from durable cache after provider failure")
                warnings.append("provider unavailable; showing cached results")
            else:
                reasoning_log.append(f"normalized {len(candidates)} candidate(s) from provider response")

        # Build audit trail
        audit: dict[str, Any] = {
            "endpoint": metadata.get("endpoint", "unknown"),
            "field_mask": metadata.get("field_mask", GOOGLE_PLACES_FIELD_MASK),
        }
        if "fallback_reason" in metadata:
            audit["fallback_reason"] = metadata["fallback_reason"]
        if fallback_source in ("cache", "cache_stale"):
            audit["fallback_source"] = fallback_source
        if "staleness_seconds" in metadata:
            audit["staleness_seconds"] = metadata["staleness_seconds"]
        if "circuit_state" in metadata:
            audit["circuit_state"] = metadata["circuit_state"]
        if "details_hydrated" in metadata:
            audit["details_hydrated"] = metadata["details_hydrated"]

        # Determine credential status for diagnostics
        api_key = self._api_key()
        credential_status = "live" if api_key else "blocked"

        # Build enriched request_metadata with full diagnostic keys
        request_metadata: dict[str, Any] = {
            "endpoint": metadata.get("endpoint", "unknown"),
            "field_mask": metadata.get("field_mask", GOOGLE_PLACES_FIELD_MASK),
            "credential_status": credential_status,
            "provider_attempted": PlaceToolSource.GOOGLE_PLACES.value,
            "result_count": len(candidates) if candidates else 0,
            "provider_contract_version": GOOGLE_PLACES_PROVIDER_CONTRACT_VERSION,
            "language_code": getattr(request, "language_code", None),
            "max_result_count": getattr(request, "max_result_count", None),
        }
        if fallback_source:
            request_metadata["fallback_source"] = fallback_source
        if "fallback_reason" in metadata:
            request_metadata["fallback_reason"] = metadata["fallback_reason"]

        return SearchPlacesToolResult(
            status=status,
            source=PlaceToolSource.CACHE if fallback_source in ("cache", "cache_stale") else PlaceToolSource.GOOGLE_PLACES,
            provider_status=ProviderStatus(),
            interpreted_query=getattr(request, "query", None),
            request_metadata=request_metadata,
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
            audit=audit,
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
        primary_type_display_name=_display_name(place.get("primaryTypeDisplayName")),
        formatted_address=_string(place.get("formattedAddress")),
        short_formatted_address=_string(place.get("shortFormattedAddress")),
        location=location,
        rating=_float(place.get("rating")),
        user_rating_count=_int(place.get("userRatingCount")),
        price_level=_price_level_google(place.get("priceLevel")),
        open_now=_open_now_google(place),
        business_status=_string(place.get("businessStatus")),
        current_opening_hours=_safe_dict(place.get("currentOpeningHours")),
        regular_opening_hours=_safe_dict(place.get("regularOpeningHours")),
        payment_options=_bool_dict(place.get("paymentOptions")),
        parking_options=_bool_dict(place.get("parkingOptions")),
        editorial_summary=_localized_text(place.get("editorialSummary")),
        generative_summary=_summary_text(place.get("generativeSummary")),
        review_summary=_summary_text(place.get("reviewSummary")),
        reviews=_reviews(place.get("reviews")),
        photos=_photos(place.get("photos")),
        takeout=_bool_or_none(place.get("takeout")),
        delivery=_bool_or_none(place.get("delivery")),
        dine_in=_bool_or_none(place.get("dineIn")),
        reservable=_bool_or_none(place.get("reservable")),
        serves_breakfast=_bool_or_none(place.get("servesBreakfast")),
        serves_lunch=_bool_or_none(place.get("servesLunch")),
        serves_dinner=_bool_or_none(place.get("servesDinner")),
        serves_beer=_bool_or_none(place.get("servesBeer")),
        serves_wine=_bool_or_none(place.get("servesWine")),
        serves_vegetarian_food=_bool_or_none(place.get("servesVegetarianFood")),
        accessibility_options=dict(accessibility),
        national_phone_number=_string(place.get("nationalPhoneNumber")),
        international_phone_number=_string(place.get("internationalPhoneNumber")),
        map_uri=_string(place.get("googleMapsUri")),
        website_uri=_string(place.get("websiteUri")),
        fairness_tags=accessibility_tags or ["accessibility_unknown"],
        route_context=RouteContext(origin=origin, distance_meters=distance_meters) if distance_meters is not None else None,
    )


def _safe_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None

def _bool_dict(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict):
        return {}
    return {str(k): v for k, v in value.items() if isinstance(v, bool)}

def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None

def _localized_text(value: Any) -> str | None:
    if isinstance(value, dict):
        return _string(value.get("text"))
    return _string(value)

def _summary_text(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    return _localized_text(value.get("overview") or value.get("summary") or value.get("description") or value)

def _reviews(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    reviews: list[dict[str, Any]] = []
    for item in value[:5]:
        if not isinstance(item, dict):
            continue
        text = _localized_text(item.get("text") or item.get("originalText"))
        author = _string(item.get("authorAttribution", {}).get("displayName")) if isinstance(item.get("authorAttribution"), dict) else None
        reviews.append({
            "rating": _float(item.get("rating")),
            "text": text[:500] if text else None,
            "author": author,
            "relative_publish_time": _string(item.get("relativePublishTimeDescription")),
        })
    return reviews

def _photos(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value[:10]:
        if isinstance(item, dict):
            name = _string(item.get("name"))
            if name:
                names.append(name)
    return names

def _merge_place_candidate(base: PlaceCandidate, details: PlaceCandidate) -> PlaceCandidate:
    data = base.model_dump()
    detail_data = details.model_dump()
    for key, value in detail_data.items():
        if value not in (None, [], {}):
            data[key] = value
    return PlaceCandidate.model_validate(data)

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


# ---------------------------------------------------------------------------
# Goong Places API fallback provider
# ---------------------------------------------------------------------------

GOONG_PLACES_BASE_URL = "https://api.goong.io"
GOONG_TEXT_SEARCH_PATH = "/place/search"
GOONG_NEARBY_SEARCH_PATH = "/place/nearby"
GOONG_DETAILS_PATH = "/place/detail"


class GoongPlacesService:
    """Goong Places API fallback provider for text/nearby search and details.

    Called only when Google Places is unavailable (missing credentials,
    auth rejected, quota exceeded, timeout, malformed response, or upstream error)
    AND GOONG_API_KEY is configured.

    Returns the same SearchPlacesToolResult envelope as GooglePlacesService
    with source=goong_places and metadata tracking primary_source=google_places,
    fallback_source=goong_places, and fallback_reason.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: PlacesHttpClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or HttpxPlacesClient(base_url=GOONG_PLACES_BASE_URL)

    def _api_key(self) -> str | None:
        key = self._settings.GOONG_API_KEY.strip()
        return key if key else None

    async def text_search(self, request: PlaceSearchRequest) -> SearchPlacesToolResult:
        api_key = self._api_key()
        retrieved_at = datetime.now(UTC)
        metadata: dict[str, Any] = {
            "endpoint": "goong_text_search",
            "primary_source": PlaceToolSource.GOOGLE_PLACES.value,
        }
        if not api_key:
            return self._credential_error(request, retrieved_at, metadata)

        params: dict[str, Any] = {
            "api_key": api_key,
            "input": request.query,
            "location": f"{request.location_bias.lat},{request.location_bias.lng}",
            "radius": request.radius_meters,
            "limit": request.max_result_count,
        }
        if request.language_code:
            params["locale"] = request.language_code
        if request.included_type:
            params["types"] = request.included_type

        return await self._execute_get_search(
            operation="goong_text_search",
            path=GOONG_TEXT_SEARCH_PATH,
            params=params,
            request=request,
            origin=request.location_bias,
            retrieved_at=retrieved_at,
            metadata=metadata,
        )

    async def nearby_search(self, request: PlaceNearbyRequest) -> SearchPlacesToolResult:
        api_key = self._api_key()
        retrieved_at = datetime.now(UTC)
        metadata: dict[str, Any] = {
            "endpoint": "goong_nearby_search",
            "primary_source": PlaceToolSource.GOOGLE_PLACES.value,
        }
        if not api_key:
            return self._credential_error(request, retrieved_at, metadata)

        params: dict[str, Any] = {
            "api_key": api_key,
            "location": f"{request.center.lat},{request.center.lng}",
            "radius": request.radius_meters,
            "limit": request.max_result_count,
        }
        if request.language_code:
            params["locale"] = request.language_code
        if request.included_type:
            params["types"] = request.included_type

        return await self._execute_get_search(
            operation="goong_nearby_search",
            path=GOONG_NEARBY_SEARCH_PATH,
            params=params,
            request=request,
            origin=request.center,
            retrieved_at=retrieved_at,
            metadata=metadata,
        )

    async def details(self, request: PlaceDetailsRequest) -> SearchPlacesToolResult:
        api_key = self._api_key()
        retrieved_at = datetime.now(UTC)
        metadata: dict[str, Any] = {"endpoint": "goong_detail", "primary_source": PlaceToolSource.GOOGLE_PLACES.value}
        if not api_key:
            return self._credential_error(request, retrieved_at, metadata)

        place_id = request.place_id.removeprefix("places/")
        params = {"api_key": api_key, "place_id": place_id}
        if request.language_code:
            params["locale"] = request.language_code

        try:
            response = await self._client.get(
                GOONG_DETAILS_PATH,
                headers={"Content-Type": "application/json"},
                params=params,
            )
        except httpx.TimeoutException:
            return self._safe_error(request, retrieved_at, metadata, "timeout", "Goong Places request timed out.", True)
        except Exception:
            return self._safe_error(request, retrieved_at, metadata, "upstream_error", "Goong Places request failed.", True)

        status_code = getattr(response, "status_code", 200)
        if status_code in (401, 403):
            return self._safe_error(request, retrieved_at, metadata, "auth_error", "Goong Places rejected the configured credentials.", False)
        if status_code == 429:
            return self._safe_error(request, retrieved_at, metadata, "quota_exceeded", "Goong Places quota was exceeded.", True)
        if status_code >= 400:
            return self._safe_error(request, retrieved_at, metadata, "upstream_error", "Goong Places returned an error.", True)

        try:
            payload = response.json()
        except Exception:
            return self._safe_error(request, retrieved_at, metadata, "malformed_response", "Goong Places returned malformed data.", True)

        result = payload.get("result") if isinstance(payload, dict) else None
        if result is None or not isinstance(result, dict):
            return self._safe_error(request, retrieved_at, metadata, "malformed_response", "Goong Places returned an unexpected shape.", True)

        candidate = _normalize_goong_place(result, origin=None)
        if not candidate:
            return self._response(
                status=PlaceToolStatus.EMPTY, request=request, retrieved_at=retrieved_at,
                metadata={**metadata, "error_code": "no_results"},
            )

        return self._response(
            status=PlaceToolStatus.OK, request=request, retrieved_at=retrieved_at,
            metadata=metadata, candidates=[candidate],
            primary_source=PlaceToolSource.GOOGLE_PLACES,
        )

    async def _execute_get_search(
        self,
        *,
        operation: str,
        path: str,
        params: dict[str, Any],
        request: PlaceSearchRequest | PlaceNearbyRequest,
        origin: LatLng,
        retrieved_at: datetime,
        metadata: dict[str, Any],
    ) -> SearchPlacesToolResult:
        try:
            response = await self._client.get(path, headers={"Content-Type": "application/json"}, params=params)
        except httpx.TimeoutException:
            return self._safe_error(request, retrieved_at, metadata, "timeout", "Goong Places request timed out.", True)
        except Exception:
            return self._safe_error(request, retrieved_at, metadata, "upstream_error", "Goong Places request failed.", True)

        status_code = getattr(response, "status_code", 200)
        if status_code in (401, 403):
            return self._safe_error(request, retrieved_at, metadata, "auth_error", "Goong Places rejected the configured credentials.", False)
        if status_code == 429:
            return self._safe_error(request, retrieved_at, metadata, "quota_exceeded", "Goong Places quota was exceeded.", True)
        if status_code >= 400:
            return self._safe_error(request, retrieved_at, metadata, "upstream_error", "Goong Places returned an error.", True)

        try:
            payload = response.json()
        except Exception:
            return self._safe_error(request, retrieved_at, metadata, "malformed_response", "Goong Places returned malformed data.", True)

        if not isinstance(payload, dict):
            return self._safe_error(request, retrieved_at, metadata, "malformed_response", "Goong Places returned an unexpected shape.", True)

        # Goong returns status field in response
        goong_status = payload.get("status", "")
        if goong_status not in ("OK", "ZERO_RESULTS", ""):
            error_msg = payload.get("error", {}).get("message", "Goong Places error")
            return self._safe_error(request, retrieved_at, metadata, "upstream_error", f"Goong Places error: {error_msg}", True)

        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list) or not raw_results:
            return self._response(
                status=PlaceToolStatus.EMPTY if goong_status == "ZERO_RESULTS" else PlaceToolStatus.OK,
                request=request, retrieved_at=retrieved_at,
                metadata={**metadata, "error_code": "no_results"},
            )

        candidates: list[PlaceCandidate] = []
        max_count = getattr(request, "max_result_count", 10)
        for raw_place in raw_results[:max_count]:
            if not isinstance(raw_place, dict):
                continue
            candidate = _normalize_goong_place(raw_place, origin=origin)
            if candidate:
                candidates.append(candidate)

        if not candidates:
            return self._response(
                status=PlaceToolStatus.EMPTY, request=request, retrieved_at=retrieved_at,
                metadata={**metadata, "error_code": "no_results"},
            )

        return self._response(
            status=PlaceToolStatus.OK, request=request, retrieved_at=retrieved_at,
            metadata=metadata, candidates=candidates,
            primary_source=PlaceToolSource.GOOGLE_PLACES,
        )

    def _credential_error(self, request: Any, retrieved_at: datetime, metadata: dict[str, Any]) -> SearchPlacesToolResult:
        return self._response(
            status=PlaceToolStatus.CREDENTIALS_BLOCKED, request=request, retrieved_at=retrieved_at,
            metadata={**metadata, "error_code": "missing_goong_api_key"},
            error=PlaceToolError(code="missing_goong_api_key", message="Goong Places credentials are not configured.", retryable=False),
            primary_source=PlaceToolSource.GOOGLE_PLACES,
        )

    def _safe_error(self, request: Any, retrieved_at: datetime, metadata: dict[str, Any], code: str, message: str, retryable: bool) -> SearchPlacesToolResult:
        return self._response(
            status=PlaceToolStatus.UPSTREAM_ERROR, request=request, retrieved_at=retrieved_at,
            metadata={**metadata, "error_code": code},
            error=PlaceToolError(code=code, message=message, retryable=retryable),
            primary_source=PlaceToolSource.GOOGLE_PLACES,
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
        primary_source: PlaceToolSource = PlaceToolSource.GOOGLE_PLACES,
    ) -> SearchPlacesToolResult:
        reasoning_log: list[str] = []
        warnings: list[str] = []
        if error:
            reasoning_log.append(f"goong error: {error.code} — {error.message}")
        if status == PlaceToolStatus.OK and candidates:
            reasoning_log.append(f"normalized {len(candidates)} candidate(s) from Goong fallback")
        elif status == PlaceToolStatus.EMPTY:
            reasoning_log.append("Goong fallback returned zero usable places")
        elif status == PlaceToolStatus.CREDENTIALS_BLOCKED:
            reasoning_log.append("Goong credentials not configured — fallback unavailable")

        request_metadata: dict[str, Any] = {
            "endpoint": metadata.get("endpoint", "unknown"),
            "credential_status": "live" if self._api_key() else "blocked",
            "provider_attempted": PlaceToolSource.GOONG_PLACES.value,
            "primary_source": primary_source.value,
            "fallback_source": PlaceToolSource.GOONG_PLACES.value,
            "result_count": len(candidates) if candidates else 0,
            "language_code": getattr(request, "language_code", None),
            "max_result_count": getattr(request, "max_result_count", None),
        }

        return SearchPlacesToolResult(
            status=status,
            source=PlaceToolSource.GOONG_PLACES,
            provider_status=ProviderStatus(),
            interpreted_query=getattr(request, "query", None),
            request_metadata=request_metadata,
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
            audit={"endpoint": metadata.get("endpoint", "unknown"), "fallback_from": primary_source.value},
            retrieved_at=retrieved_at,
        )


def _normalize_goong_place(place: dict[str, Any], *, origin: LatLng | None = None) -> PlaceCandidate | None:
    """Normalize one Goong Places place object into a PlaceCandidate.

    Goong Places response fields:
    - place_id, name, formatted_address
    - geometry.location.{lat, lng}
    - rating, types[], vicinity
    - photos[] (not mapped — provider-specific)
    """
    place_id = _string(place.get("place_id"))
    if not place_id:
        return None

    display_name = _string(place.get("name")) or place_id

    location = _goong_location(place.get("geometry"))
    distance_meters: int | None = None
    if origin and location:
        distance_meters = _haversine_meters(origin, location)

    types = [item for item in place.get("types", []) if isinstance(item, str)] if isinstance(place.get("types"), list) else []

    return PlaceCandidate(
        place_id=place_id,
        resource_name=f"places/{place_id}",
        display_name=display_name,
        types=types,
        primary_type=types[0] if types else None,
        formatted_address=_string(place.get("formatted_address")) or _string(place.get("vicinity")),
        short_formatted_address=None,
        location=location,
        rating=_float(place.get("rating")),
        user_rating_count=_int(place.get("user_ratings_total")),
        price_level=None,  # Goong does not provide price level
        open_now=_goong_open_hours(place.get("opening_hours")),
        business_status=None,
        accessibility_options={},
        national_phone_number=_string(place.get("international_phone_number")) or _string(place.get("formatted_phone_number")),
        international_phone_number=_string(place.get("international_phone_number")),
        map_uri=f"https://map.goong.io/place?pid={place_id}",
        website_uri=_string(place.get("website")),
        fairness_tags=["accessibility_unknown"],
        route_context=RouteContext(origin=origin, distance_meters=distance_meters) if distance_meters is not None else None,
    )


def _goong_location(geometry: Any) -> LatLng | None:
    """Extract lat/lng from Goong geometry object."""
    if not isinstance(geometry, dict):
        return None
    loc = geometry.get("location")
    if not isinstance(loc, dict):
        return None
    lat = loc.get("lat")
    lng = loc.get("lng")
    if lat is None or lng is None:
        return None
    try:
        return LatLng(lat=float(lat), lng=float(lng))
    except (TypeError, ValueError):
        return None


def _goong_open_hours(opening_hours: Any) -> bool | None:
    """Extract open_now from Goong opening_hours object."""
    if not isinstance(opening_hours, dict):
        return None
    open_now = opening_hours.get("open_now")
    if isinstance(open_now, bool):
        return open_now
    return None


# ---------------------------------------------------------------------------
# DualPlacesService — Google-first with Goong fallback composition
# ---------------------------------------------------------------------------

_GOOGLE_FALLBACK_TRIGGERS = frozenset({
    PlaceToolStatus.CREDENTIALS_BLOCKED,
    PlaceToolStatus.UPSTREAM_ERROR,
    PlaceToolStatus.UNAVAILABLE,
})


class DualPlacesService:
    """Composition layer: Google Places API New primary with Goong fallback.

    When GOOGLE_PLACES_API_KEY is present:
        1. Call Google Places API first
        2. On success (OK/EMPTY) → return Google result with source=google_places
        3. On failure (credentials_blocked, upstream_error, unavailable) → try Goong

    When GOOGLE_PLACES_API_KEY is absent or blank:
        1. Skip Google, call Goong directly if GOONG_API_KEY is configured
        2. If Goong also unavailable → return honest unavailable

    Metadata tracking:
        - primary_source: always google_places (or none if Google skipped)
        - fallback_source: goong_places if Goong was called
        - fallback_reason: why Google was bypassed
        - credential_status: live/blocked/unavailable
    """

    def __init__(
        self,
        *,
        google_service: GooglePlacesService | None = None,
        goong_service: GoongPlacesService | None = None,
        settings: Settings | None = None,
        place_cache: Any | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._google = google_service or GooglePlacesService(settings=self._settings, place_cache=place_cache)
        self._goong = goong_service or GoongPlacesService(settings=self._settings)
        self._place_cache = place_cache

    def _has_google_key(self) -> bool:
        key = self._settings.GOOGLE_PLACES_API_KEY.strip()
        return bool(key)

    def _has_goong_key(self) -> bool:
        key = self._settings.GOONG_API_KEY.strip()
        return bool(key)

    async def text_search(self, request: PlaceSearchRequest) -> SearchPlacesToolResult:
        """Execute text search with Google-first + Goong fallback strategy."""
        retrieved_at = datetime.now(UTC)

        # If Google key is configured, try Google first
        if self._has_google_key():
            google_result = await self._google.text_search(request)

            # Success path: OK or EMPTY → return Google result directly
            if google_result.status in (PlaceToolStatus.OK, PlaceToolStatus.EMPTY):
                return google_result

            # Failure path: try Goong fallback
            fallback_reason = self._classify_google_failure(google_result)
            logger.info(
                "places.google_failed",
                status=google_result.status.value,
                fallback_reason=fallback_reason,
            )
            return await self._goong_fallback(
                operation="text_search",
                request=request,
                google_result=google_result,
                fallback_reason=fallback_reason,
                retrieved_at=retrieved_at,
            )

        # Google key absent — go directly to Goong
        if self._has_goong_key():
            logger.info("places.google_skipped", reason="credential_missing")
            return await self._goong_only(
                operation="text_search", request=request, retrieved_at=retrieved_at,
            )

        # Neither provider configured
        return self._no_provider_response(request, retrieved_at)

    async def nearby_search(self, request: PlaceNearbyRequest) -> SearchPlacesToolResult:
        """Execute nearby search with Google-first + Goong fallback strategy."""
        retrieved_at = datetime.now(UTC)

        if self._has_google_key():
            google_result = await self._google.nearby_search(request)
            if google_result.status in (PlaceToolStatus.OK, PlaceToolStatus.EMPTY):
                return google_result

            fallback_reason = self._classify_google_failure(google_result)
            return await self._goong_fallback(
                operation="nearby_search",
                request=request,
                google_result=google_result,
                fallback_reason=fallback_reason,
                retrieved_at=retrieved_at,
            )

        if self._has_goong_key():
            return await self._goong_only(
                operation="nearby_search", request=request, retrieved_at=retrieved_at,
            )

        return self._no_provider_response(request, retrieved_at)

    async def details(self, request: PlaceDetailsRequest) -> SearchPlacesToolResult:
        """Execute place details with Google-first + Goong fallback strategy."""
        retrieved_at = datetime.now(UTC)

        if self._has_google_key():
            google_result = await self._google.details(request)
            if google_result.status in (PlaceToolStatus.OK, PlaceToolStatus.EMPTY):
                return google_result

            fallback_reason = self._classify_google_failure(google_result)
            return await self._goong_fallback(
                operation="details",
                request=request,
                google_result=google_result,
                fallback_reason=fallback_reason,
                retrieved_at=retrieved_at,
            )

        if self._has_goong_key():
            return await self._goong_only(
                operation="details", request=request, retrieved_at=retrieved_at,
            )

        return self._no_provider_response(request, retrieved_at)

    def _classify_google_failure(self, result: SearchPlacesToolResult) -> str:
        """Classify Google failure for fallback_reason metadata."""
        if result.status == PlaceToolStatus.CREDENTIALS_BLOCKED:
            return "google_credentials_blocked"
        if result.status == PlaceToolStatus.UPSTREAM_ERROR:
            error_code = result.audit.get("error_code", result.request_metadata.get("error_code", "unknown"))
            return f"google_upstream_error:{error_code}"
        if result.status == PlaceToolStatus.UNAVAILABLE:
            fallback_reason = result.audit.get("fallback_reason", "unknown")
            return f"google_unavailable:{fallback_reason}"
        return f"google_status_{result.status.value}"

    async def _goong_fallback(
        self,
        *,
        operation: str,
        request: Any,
        google_result: SearchPlacesToolResult,
        fallback_reason: str,
        retrieved_at: datetime,
    ) -> SearchPlacesToolResult:
        """Try Goong as fallback after Google failure. Enriches metadata."""
        if not self._has_goong_key():
            logger.info("places.goong_unavailable", reason="credential_missing")
            return self._enrich_google_failure(google_result, fallback_reason, retrieved_at)

        logger.info("places.goong_fallback", reason=fallback_reason)

        try:
            if operation == "text_search":
                goong_result = await self._goong.text_search(request)
            elif operation == "nearby_search":
                goong_result = await self._goong.nearby_search(request)
            else:
                goong_result = await self._goong.details(request)
        except Exception as exc:  # noqa: BLE001
            logger.warning("places.goong_fallback_error", error_type=type(exc).__name__)
            return self._enrich_google_failure(google_result, fallback_reason, retrieved_at)

        # Enrich Goong result with fallback metadata
        if goong_result.status in (PlaceToolStatus.OK, PlaceToolStatus.EMPTY):
            return self._enrich_fallback_success(goong_result, fallback_reason)

        # Goong also failed — return enriched Google failure
        return self._enrich_dual_failure(goong_result, fallback_reason, retrieved_at)

    async def _goong_only(
        self,
        *,
        operation: str,
        request: Any,
        retrieved_at: datetime,
    ) -> SearchPlacesToolResult:
        """Call Goong directly when Google key is absent. Enrich metadata."""
        try:
            if operation == "text_search":
                result = await self._goong.text_search(request)
            elif operation == "nearby_search":
                result = await self._goong.nearby_search(request)
            else:
                result = await self._goong.details(request)
        except Exception as exc:  # noqa: BLE001
            logger.warning("places.goong_only_error", error_type=type(exc).__name__)
            return self._no_provider_response(request, retrieved_at)

        # Enrich with primary_source metadata even for Goong-only path
        return self._enrich_fallback_success(result, "google_credential_missing")

    def _enrich_fallback_success(
        self,
        result: SearchPlacesToolResult,
        fallback_reason: str,
    ) -> SearchPlacesToolResult:
        """Enrich a successful Goong result with primary/fallback metadata."""
        result.request_metadata["primary_source"] = PlaceToolSource.GOOGLE_PLACES.value
        result.request_metadata["fallback_source"] = PlaceToolSource.GOONG_PLACES.value
        result.request_metadata["fallback_reason"] = fallback_reason
        result.request_metadata["provider_attempted"] = f"{PlaceToolSource.GOOGLE_PLACES.value}->{PlaceToolSource.GOONG_PLACES.value}"
        result.audit["primary_source"] = PlaceToolSource.GOOGLE_PLACES.value
        result.audit["fallback_source"] = PlaceToolSource.GOONG_PLACES.value
        result.audit["fallback_reason"] = fallback_reason
        return result

    def _enrich_google_failure(
        self,
        google_result: SearchPlacesToolResult,
        fallback_reason: str,
        retrieved_at: datetime,
    ) -> SearchPlacesToolResult:
        """Enrich Google failure when Goong is unavailable."""
        google_result.request_metadata["primary_source"] = PlaceToolSource.GOOGLE_PLACES.value
        google_result.request_metadata["fallback_source"] = "none"
        google_result.request_metadata["fallback_reason"] = fallback_reason
        google_result.audit["primary_source"] = PlaceToolSource.GOOGLE_PLACES.value
        google_result.audit["fallback_source"] = "none"
        google_result.audit["fallback_reason"] = fallback_reason
        return google_result

    def _enrich_dual_failure(
        self,
        goong_result: SearchPlacesToolResult,
        fallback_reason: str,
        retrieved_at: datetime,
    ) -> SearchPlacesToolResult:
        """Both providers failed — return honest UNAVAILABLE with dual-failure metadata."""
        return SearchPlacesToolResult(
            status=PlaceToolStatus.UNAVAILABLE,
            source=PlaceToolSource.GOOGLE_PLACES,
            provider_status=ProviderStatus(),
            interpreted_query=getattr(goong_result, "interpreted_query", None),
            request_metadata={
                "primary_source": PlaceToolSource.GOOGLE_PLACES.value,
                "fallback_source": PlaceToolSource.GOONG_PLACES.value,
                "fallback_reason": fallback_reason,
                "provider_attempted": f"{PlaceToolSource.GOOGLE_PLACES.value}->{PlaceToolSource.GOONG_PLACES.value}",
                "credential_status": "unavailable",
                "result_count": 0,
            },
            candidates=[],
            warnings=["Both Google and Goong places providers are unavailable."],
            reasoning_log=[
                f"google failed: {fallback_reason}",
                f"goong fallback also failed: {goong_result.status.value}",
            ],
            explanation=None,
            place_recommendation_status=PlaceRecommendationStatus(
                provider_places_returned=0,
                candidates_after_normalization=0,
                filters_applied=[],
                reason=f"dual_provider_failure: google={fallback_reason}, goong={goong_result.status.value}",
            ),
            audit={
                "primary_source": PlaceToolSource.GOOGLE_PLACES.value,
                "fallback_source": PlaceToolSource.GOONG_PLACES.value,
                "fallback_reason": fallback_reason,
                "google_status": goong_result.status.value,
            },
            retrieved_at=retrieved_at,
        )

    def _no_provider_response(self, request: Any, retrieved_at: datetime) -> SearchPlacesToolResult:
        """Neither Google nor Goong credentials configured."""
        return SearchPlacesToolResult(
            status=PlaceToolStatus.CREDENTIALS_BLOCKED,
            source=PlaceToolSource.GOOGLE_PLACES,
            provider_status=ProviderStatus(),
            interpreted_query=getattr(request, "query", None),
            request_metadata={
                "primary_source": PlaceToolSource.GOOGLE_PLACES.value,
                "fallback_source": "none",
                "fallback_reason": "no_provider_configured",
                "credential_status": "blocked",
                "result_count": 0,
            },
            candidates=[],
            warnings=["No Places API credentials configured (Google or Goong)."],
            reasoning_log=["Google API key not configured and Goong API key not configured."],
            explanation=None,
            place_recommendation_status=PlaceRecommendationStatus(
                provider_places_returned=0,
                candidates_after_normalization=0,
                filters_applied=[],
                reason="no_provider_configured",
            ),
            audit={
                "primary_source": PlaceToolSource.GOOGLE_PLACES.value,
                "fallback_source": "none",
                "fallback_reason": "no_provider_configured",
            },
            retrieved_at=retrieved_at,
        )
