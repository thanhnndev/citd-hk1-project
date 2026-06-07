"""Google Routes API client with circuit breaker and candidate enrichment."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any, Protocol

import httpx

from app.core.config import Settings, get_settings
from app.models.places import PlaceCandidate, RouteContext
from app.models.request import LatLng

logger = logging.getLogger(__name__)

ROUTES_BASE_URL = "https://routes.googleapis.com"
DISTANCE_MATRIX_PATH = "/distanceMatrix/v2:computeRouteMatrix"
FIELD_MASK = "originIndex,destinationIndex,duration,distanceMeters,status,condition"

# ── Circuit breaker thresholds ─────────────────────────────────
FAILURE_WINDOW_SECONDS = 60   # Look-back window for counting failures
FAILURE_THRESHOLD = 3         # Trips circuit after this many failures in window
COOLDOWN_SECONDS = 300        # How long to stay open before trying again (5 min)


class RoutesHttpClient(Protocol):
    """Minimal async HTTP seam so tests and agents can substitute a mock client."""

    async def post(
        self,
        path: str,
        *,
        json: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> Any: ...


class HttpxRoutesClient:
    """Thin httpx-backed client for Google Routes API."""

    def __init__(self, *, base_url: str = ROUTES_BASE_URL, timeout: float = 10.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def post(
        self,
        path: str,
        *,
        json: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> httpx.Response:
        return await self._client.post(path, json=json, headers=headers)

    async def aclose(self) -> None:
        await self._client.aclose()


class CircuitBreaker:
    """Time-windowed circuit breaker for the Routes API."""

    def __init__(
        self,
        *,
        threshold: int = FAILURE_THRESHOLD,
        window: float = FAILURE_WINDOW_SECONDS,
        cooldown: float = COOLDOWN_SECONDS,
    ) -> None:
        self._threshold = threshold
        self._window = window
        self._cooldown = cooldown
        self._failures: list[float] = []
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        self._prune()
        if self._opened_at is not None:
            if time.monotonic() - self._opened_at >= self._cooldown:
                self._opened_at = None
                return False
            return True
        return len(self._failures) >= self._threshold

    def record_failure(self) -> None:
        now = time.monotonic()
        self._failures.append(now)
        if len(self._failures) >= self._threshold:
            if self._opened_at is None:
                logger.warning(
                    "circuit_breaker_open",
                    extra={
                        "failure_count": len(self._failures),
                        "window_seconds": self._window,
                    },
                )
            self._opened_at = now

    def record_success(self) -> None:
        self._failures.clear()
        self._opened_at = None

    def reset(self) -> None:
        self._failures.clear()
        self._opened_at = None

    def _prune(self) -> None:
        cutoff = time.monotonic() - self._window
        self._failures = [ts for ts in self._failures if ts > cutoff]


class GoogleRoutesService:
    """Server-side Google Routes service for computing real driving distances."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: RoutesHttpClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or HttpxRoutesClient()
        self._circuit_breaker = CircuitBreaker()

    @property
    def is_open(self) -> bool:
        return self._circuit_breaker.is_open

    async def computeRouteMatrix(
        self,
        origin: LatLng,
        destinations: list[LatLng],
    ) -> list[dict[str, Any]]:
        api_key = self._get_api_key()
        if api_key is None:
            logger.warning("routes_api_skip", extra={"reason": "credential-blocked"})
            return []

        if self._circuit_breaker.is_open:
            logger.warning("circuit_breaker_open", extra={"reason": "circuit-open"})
            return []

        if not destinations:
            return []

        body = {
            "origins": [
                {
                    "waypoint": {
                        "location": {
                            "latLng": {
                                "latitude": origin.lat,
                                "longitude": origin.lng
                            }
                        }
                    }
                }
            ],
            "destinations": [
                {
                    "waypoint": {
                        "location": {
                            "latLng": {
                                "latitude": dest.lat,
                                "longitude": dest.lng
                            }
                        }
                    }
                }
                for dest in destinations
            ],
            "travelMode": "DRIVE"
        }

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": FIELD_MASK
        }

        try:
            response = await self._client.post(
                DISTANCE_MATRIX_PATH, json=body, headers=headers
            )
        except httpx.TimeoutException:
            logger.warning("route_timeout")
            self._circuit_breaker.record_failure()
            return []
        except httpx.RequestError:
            logger.warning("route_transport_error")
            self._circuit_breaker.record_failure()
            return []

        status_code = getattr(response, "status_code", 200)

        if status_code == 429:
            logger.warning("route_429")
            self._circuit_breaker.record_failure()
            return []
        if status_code >= 500:
            logger.warning("route_5xx")
            self._circuit_breaker.record_failure()
            return []
        if status_code in (401, 403):
            logger.warning("routes_api_skip", extra={"reason": "credential-blocked"})
            return []
        if status_code >= 400:
            logger.warning("routes_api_skip", extra={"reason": "client-error"})
            return []

        try:
            payload = response.json()
        except Exception:
            logger.warning("route_malformed_json")
            self._circuit_breaker.record_failure()
            return []

        results = _normalize_google_matrix(payload)
        if results is None:
            logger.warning("route_unexpected_response_shape")
            self._circuit_breaker.record_failure()
            return []

        self._circuit_breaker.record_success()
        return results

    async def enrich_candidates(
        self,
        candidates: list[PlaceCandidate],
        origin: LatLng,
    ) -> list[PlaceCandidate]:
        routed_candidates = [c for c in candidates if c.location is not None]
        unrouted_candidates = [c for c in candidates if c.location is None]

        if not routed_candidates:
            return candidates

        api_key = self._get_api_key()
        if api_key is None:
            return candidates
        if self._circuit_breaker.is_open:
            return candidates

        destinations = [c.location for c in routed_candidates]
        results = await self.computeRouteMatrix(origin, destinations)

        # Mapping: destinationIndex to result
        result_map = {r.get("destinationIndex"): r for r in results if "destinationIndex" in r}

        computed_count = 0
        for idx, candidate in enumerate(routed_candidates):
            result = result_map.get(idx)
            if isinstance(result, dict):
                distance = result.get("distanceMeters")
                duration = result.get("durationSeconds")
                if distance is not None or duration is not None:
                    candidate.route_context = RouteContext(
                        origin=origin,
                        travel_mode="drive",
                        distance_meters=int(distance) if distance is not None else None,
                        duration_seconds=int(duration) if duration is not None else None,
                    )
                    computed_count += 1

        logger.info("route_enrichment", extra={"computed_count": computed_count})
        return routed_candidates + unrouted_candidates

    def _get_api_key(self) -> str | None:
        key = self._settings.GOOGLE_PLACES_API_KEY.strip()
        return key if key else None


def _normalize_google_matrix(payload: object) -> list[dict[str, Any]] | None:
    if not isinstance(payload, list):
        return None
    normalized: list[dict[str, Any]] = []
    for element in payload:
        if not isinstance(element, dict):
            continue
        dest_idx = element.get("destinationIndex", 0)
        status = element.get("condition", "ROUTE_EXISTS")
        result: dict[str, Any] = {"destinationIndex": dest_idx, "status": "OK" if status == "ROUTE_EXISTS" else status}
        distance = element.get("distanceMeters")
        if isinstance(distance, (int, float)):
            result["distanceMeters"] = int(distance)
        duration = element.get("duration")
        if isinstance(duration, str) and duration.endswith('s'):
            try:
                result["durationSeconds"] = int(float(duration[:-1]))
            except ValueError:
                pass
        normalized.append(result)
    return normalized

# Temporary compatibility aliases
GoongRoutesService = GoogleRoutesService

