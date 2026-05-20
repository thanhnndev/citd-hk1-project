"""Google Routes API (New) client with circuit breaker and candidate enrichment."""

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
COMPUTE_ROUTE_MATRIX_PATH = "/directions/v2:computeRouteMatrix"

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
    """Thin httpx-backed client for Google Routes API (New)."""

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
    """Time-windowed circuit breaker for the Routes API.

    - Tracks failure timestamps in a list.
    - ``is_open`` returns True when >= FAILURE_THRESHOLD failures occurred
      within the last FAILURE_WINDOW_SECONDS.
    - Once open, stays open for COOLDOWN_SECONDS before allowing another attempt.
    - ``record_success()`` clears the failure history.
    """

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

    # -- Public API -------------------------------------------------

    @property
    def is_open(self) -> bool:
        """True if the circuit is currently open (tripped or in cooldown)."""
        self._prune()
        if self._opened_at is not None:
            if time.monotonic() - self._opened_at >= self._cooldown:
                # Cooldown expired — allow a probe attempt.
                self._opened_at = None
                return False
            return True
        return len(self._failures) >= self._threshold

    def record_failure(self) -> None:
        """Record a failure. Trips the circuit if threshold is exceeded."""
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
        """Record a success — clears failure history and closes the circuit."""
        self._failures.clear()
        self._opened_at = None

    def reset(self) -> None:
        """Force-reset for testing or manual recovery."""
        self._failures.clear()
        self._opened_at = None

    def _prune(self) -> None:
        """Remove stale failure entries outside the look-back window."""
        cutoff = time.monotonic() - self._window
        self._failures = [ts for ts in self._failures if ts > cutoff]


class GoogleRoutesService:
    """Server-side Routes service for computing real driving distances.

    Usage::

        service = GoogleRoutesService()
        results = await service.computeRouteMatrix(origin, destinations)
        candidates = await service.enrich_candidates(candidates, origin)
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: RoutesHttpClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or HttpxRoutesClient()
        self._circuit_breaker = CircuitBreaker()

    # -- Circuit breaker exposed as a property ---------------------

    @property
    def is_open(self) -> bool:
        """True when the circuit breaker is tripped or in cooldown."""
        return self._circuit_breaker.is_open

    # -- Core API ---------------------------------------------------

    async def computeRouteMatrix(
        self,
        origin: LatLng,
        destinations: list[LatLng],
    ) -> list[dict[str, Any]]:
        """Compute driving distances and durations from one origin to many destinations.

        POSTs to ``https://routes.googleapis.com/directions/v2:computeRouteMatrix``.

        Returns a list of result dicts (one per destination, in request order).
        Each dict contains keys from the field mask:
        ``distanceMeters``, ``durationSeconds``, ``condition``, ``status``,
        ``destinationIndex``.

        On failure modes (missing key, timeout, 429, 5xx, circuit-open),
        returns an empty list.
        """
        # 1. Credential check
        api_key = self._get_api_key()
        if api_key is None:
            logger.warning(
                "routes_api_skip",
                extra={"reason": "credential-blocked"},
            )
            return []

        # 2. Circuit breaker check
        if self._circuit_breaker.is_open:
            logger.warning(
                "circuit_breaker_open",
                extra={"reason": "circuit-open"},
            )
            return []

        # 3. Build request
        body = {
            "origins": [
                {
                    "location": {
                        "latLng": {"latitude": origin.lat, "longitude": origin.lng}
                    }
                }
            ],
            "destinations": [
                {
                    "location": {
                        "latLng": {"lat": d.lat, "longitude": d.lng}
                    }
                }
                for d in destinations
            ],
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_UNAWARE",
        }

        headers = {
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "distanceMeters,durationSeconds,condition,status,destinationIndex",
            "Content-Type": "application/json",
        }

        # 4. Execute
        try:
            response = await self._client.post(
                COMPUTE_ROUTE_MATRIX_PATH, json=body, headers=headers
            )
        except httpx.TimeoutException:
            logger.warning(
                "route_timeout",
                extra={"origin": (origin.lat, origin.lng), "destination_count": len(destinations)},
            )
            self._circuit_breaker.record_failure()
            return []

        status_code = getattr(response, "status_code", 200)

        if status_code == 429:
            logger.warning(
                "route_429",
                extra={"reason": "rate-limited"},
            )
            self._circuit_breaker.record_failure()
            return []

        if status_code >= 500:
            logger.warning(
                "route_5xx",
                extra={"status_code": status_code},
            )
            self._circuit_breaker.record_failure()
            return []

        if status_code == 401 or status_code == 403:
            logger.warning(
                "routes_api_skip",
                extra={"reason": "credential-blocked", "status_code": status_code},
            )
            # Auth errors do NOT trip the circuit breaker.
            return []

        if status_code >= 400:
            logger.warning(
                "routes_api_skip",
                extra={"reason": "client-error", "status_code": status_code},
            )
            return []

        # 5. Parse response
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            logger.warning("route_malformed_json")
            self._circuit_breaker.record_failure()
            return []

        results = (
            payload if isinstance(payload, list) else payload.get("originIndex", [])
            if isinstance(payload, dict) else []
        )

        if not isinstance(results, list):
            logger.warning("route_unexpected_response_shape")
            self._circuit_breaker.record_failure()
            return []

        self._circuit_breaker.record_success()
        return results

    # -- Enrichment helper ------------------------------------------

    async def enrich_candidates(
        self,
        candidates: list[PlaceCandidate],
        origin: LatLng,
    ) -> list[PlaceCandidate]:
        """Enrich candidates with real driving distances and durations.

        Calls ``computeRouteMatrix`` with candidate locations as destinations,
        then maps results back by index and populates ``route_context`` on each
        candidate.

        If the circuit breaker is open or the API key is missing, returns
        candidates unchanged with a log warning.
        """
        # Filter candidates that have a location
        routed_candidates = [c for c in candidates if c.location is not None]
        unrouted_candidates = [c for c in candidates if c.location is None]

        if not routed_candidates:
            return candidates

        # Check early-exit conditions before making the API call
        api_key = self._get_api_key()
        if api_key is None:
            logger.warning(
                "routes_api_skip",
                extra={"reason": "credential-blocked", "candidate_count": len(routed_candidates)},
            )
            return candidates

        if self._circuit_breaker.is_open:
            logger.warning(
                "circuit_breaker_open",
                extra={"reason": "circuit-open", "candidate_count": len(routed_candidates)},
            )
            return candidates

        destinations = [c.location for c in routed_candidates]
        results = await self.computeRouteMatrix(origin, destinations)

        computed_count = 0
        for idx, candidate in enumerate(routed_candidates):
            result = results[idx] if idx < len(results) else {}
            if isinstance(result, dict) and result.get("status") in (None, "OK"):
                distance = result.get("distanceMeters")
                duration = result.get("durationSeconds")
                # Only populate route_context when we have at least one metric.
                if distance is not None or duration is not None:
                    candidate.route_context = RouteContext(
                        origin=origin,
                        travel_mode="drive",
                        distance_meters=int(distance) if distance is not None else None,
                        duration_seconds=int(duration) if duration is not None else None,
                    )
                    computed_count += 1

        logger.info(
            "route_enrichment",
            extra={
                "candidate_count": len(routed_candidates),
                "computed_count": computed_count,
            },
        )

        return routed_candidates + unrouted_candidates

    # -- Internals --------------------------------------------------

    def _get_api_key(self) -> str | None:
        key = self._settings.GOOGLE_ROUTES_API_KEY.strip()
        return key if key else None
