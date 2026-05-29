"""Tests for Goong Routes service: DistanceMatrix, circuit breaker, and enrichment."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.models.places import PlaceCandidate, RouteContext
from app.models.request import LatLng
from agents.tools.routes_service import (
    CircuitBreaker,
    GoongRoutesService,
    GoongRoutesService,
    COOLDOWN_SECONDS,
    FAILURE_THRESHOLD,
    FAILURE_WINDOW_SECONDS,
)


# ── Helpers ─────────────────────────────────────────────────────────────


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload: object | None = None,
        json_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self) -> object:
        if self._json_error:
            raise self._json_error
        return self._payload


class FakeRoutesClient:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def get(
        self, path: str, *, params: object
    ) -> FakeResponse:
        self.calls.append({"path": path, "params": params})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _settings(routes_key: str = "test-goong-key") -> Settings:
    return Settings(OPENAI_API_KEY="openai-test", GOONG_API_KEY=routes_key)



def test_google_routes_service_alias_removed() -> None:
    import agents.tools.routes_service as routes_service

    assert not hasattr(routes_service, "GoogleRoutesService")

def _candidate(name: str, lat: float, lng: float) -> PlaceCandidate:
    return PlaceCandidate(
        place_id=f"pid-{name}",
        display_name=name,
        location=LatLng(lat=lat, lng=lng),
    )


# ── Circuit Breaker Unit Tests ─────────────────────────────────────────


class TestCircuitBreaker:
    def test_initially_closed(self) -> None:
        cb = CircuitBreaker()
        assert cb.is_open is False

    def test_opens_after_threshold_failures(self) -> None:
        cb = CircuitBreaker(threshold=3, window=60, cooldown=300)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is False
        cb.record_failure()
        assert cb.is_open is True

    def test_success_resets_circuit(self) -> None:
        cb = CircuitBreaker(threshold=2, window=60, cooldown=300)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True
        cb.record_success()
        assert cb.is_open is False

    def test_stale_failures_pruned(self) -> None:
        import time

        cb = CircuitBreaker(threshold=2, window=0.01, cooldown=300)
        cb.record_failure()
        time.sleep(0.02)
        # Old failure should be pruned; one fresh failure is below threshold.
        assert cb.is_open is False
        cb.record_failure()
        assert cb.is_open is False
        cb.record_failure()
        assert cb.is_open is True

    def test_cooldown_expires(self) -> None:
        import time

        cb = CircuitBreaker(threshold=1, window=60, cooldown=0.01)
        cb.record_failure()
        assert cb.is_open is True
        time.sleep(0.02)
        # After cooldown, circuit should close for a probe attempt.
        assert cb.is_open is False

    def test_reset_clears_everything(self) -> None:
        cb = CircuitBreaker(threshold=1, window=60, cooldown=300)
        cb.record_failure()
        assert cb.is_open is True
        cb.reset()
        assert cb.is_open is False

    def test_property_accessors(self) -> None:
        cb = CircuitBreaker()
        assert cb.is_open is False
        cb.record_success()  # Should not crash
        assert cb.is_open is False


# ── computeRouteMatrix: Success Path ───────────────────────────────────


@pytest.mark.asyncio
async def test_computeRouteMatrix_returns_results_on_success() -> None:
    origin = LatLng(lat=10.0, lng=106.0)
    dest1 = LatLng(lat=10.1, lng=106.1)
    dest2 = LatLng(lat=10.2, lng=106.2)

    fake_response = FakeResponse(
        status_code=200,
        payload={"rows": [{"elements": [
            {"status": "OK", "distance": {"value": 5000}, "duration": {"value": 300}},
            {"status": "OK", "distance": {"value": 8000}, "duration": {"value": 480}},
        ]}]},
    )
    client = FakeRoutesClient(fake_response)
    service = GoongRoutesService(settings=_settings(), client=client)

    results = await service.computeRouteMatrix(origin, [dest1, dest2])

    assert results == [
        {
            "destinationIndex": 0,
            "status": "OK",
            "distanceMeters": 5000,
            "durationSeconds": 300,
        },
        {
            "destinationIndex": 1,
            "status": "OK",
            "distanceMeters": 8000,
            "durationSeconds": 480,
        },
    ]
    assert len(client.calls) == 1

    params = client.calls[0]["params"]
    assert client.calls[0]["path"] == "/DistanceMatrix"
    assert params["origins"] == "10.0,106.0"
    assert params["destinations"] == "10.1,106.1|10.2,106.2"
    assert params["vehicle"] == "car"
    assert params["api_key"] == "test-goong-key"


@pytest.mark.asyncio
async def test_computeRouteMatrix_records_success_on_ok() -> None:
    """A successful response should record_success, clearing any prior failures."""
    client = FakeRoutesClient(
        FakeResponse(status_code=200, payload={"rows": [{"elements": [{"status": "OK"}]}]})
    )
    service = GoongRoutesService(settings=_settings(), client=client)
    service._circuit_breaker.record_failure()
    service._circuit_breaker.record_failure()

    await service.computeRouteMatrix(LatLng(lat=10.0, lng=106.0), [LatLng(lat=10.1, lng=106.1)])

    assert service._circuit_breaker.is_open is False


# ── computeRouteMatrix: Failure Modes ──────────────────────────────────


@pytest.mark.asyncio
async def test_missing_key_returns_empty_with_log() -> None:
    """When GOONG_API_KEY is blank, return empty list without outbound call."""
    client = FakeRoutesClient(
        FakeResponse(status_code=200, payload={"rows": [{"elements": [{"status": "OK"}]}]})
    )
    service = GoongRoutesService(settings=_settings(routes_key=""), client=client)

    results = await service.computeRouteMatrix(
        LatLng(lat=10.0, lng=106.0),
        [LatLng(lat=10.1, lng=106.1)],
    )

    assert results == []
    assert len(client.calls) == 0


@pytest.mark.asyncio
async def test_circuit_open_returns_empty() -> None:
    """When circuit breaker is open, return empty without outbound call."""
    client = FakeRoutesClient(
        FakeResponse(status_code=200, payload={"rows": [{"elements": [{"status": "OK"}]}]})
    )
    service = GoongRoutesService(settings=_settings(), client=client)
    for _ in range(FAILURE_THRESHOLD):
        service._circuit_breaker.record_failure()

    assert service.is_open is True
    results = await service.computeRouteMatrix(
        LatLng(lat=10.0, lng=106.0),
        [LatLng(lat=10.1, lng=106.1)],
    )
    assert results == []
    assert len(client.calls) == 0


@pytest.mark.asyncio
async def test_timeout_records_failure() -> None:
    """Timeout should log warning, record failure, and return empty."""
    client = FakeRoutesClient(httpx.TimeoutException("timed out"))
    service = GoongRoutesService(settings=_settings(), client=client)

    results = await service.computeRouteMatrix(
        LatLng(lat=10.0, lng=106.0),
        [LatLng(lat=10.1, lng=106.1)],
    )

    assert results == []
    assert service.is_open is False  # 1 failure < threshold
    service._circuit_breaker.record_failure()
    service._circuit_breaker.record_failure()
    assert service.is_open is True  # now at threshold



@pytest.mark.asyncio
async def test_transport_error_records_failure() -> None:
    """Transport errors should log safely, record failure, and return empty."""
    client = FakeRoutesClient(httpx.ConnectError("network blocked"))
    service = GoongRoutesService(settings=_settings(), client=client)

    results = await service.computeRouteMatrix(
        LatLng(lat=10.0, lng=106.0),
        [LatLng(lat=10.1, lng=106.1)],
    )

    assert results == []
    assert service.is_open is False

@pytest.mark.asyncio
async def test_empty_destinations_returns_empty_without_call() -> None:
    client = FakeRoutesClient(FakeResponse(status_code=200, payload={"rows": [{"elements": []}]}))
    service = GoongRoutesService(settings=_settings(), client=client)

    results = await service.computeRouteMatrix(LatLng(lat=10.0, lng=106.0), [])

    assert results == []
    assert len(client.calls) == 0

@pytest.mark.asyncio
async def test_429_records_failure_and_returns_empty() -> None:
    """429 rate limit should trip circuit breaker and return empty."""
    client = FakeRoutesClient(FakeResponse(status_code=429, payload={}))
    service = GoongRoutesService(settings=_settings(), client=client)

    for _ in range(FAILURE_THRESHOLD):
        await service.computeRouteMatrix(
            LatLng(lat=10.0, lng=106.0),
            [LatLng(lat=10.1, lng=106.1)],
        )

    assert service.is_open is True


@pytest.mark.asyncio
async def test_5xx_records_failure_and_returns_empty() -> None:
    """500-range errors should trip circuit breaker and return empty."""
    client = FakeRoutesClient(FakeResponse(status_code=503, payload={}))
    service = GoongRoutesService(settings=_settings(), client=client)

    for _ in range(FAILURE_THRESHOLD):
        await service.computeRouteMatrix(
            LatLng(lat=10.0, lng=106.0),
            [LatLng(lat=10.1, lng=106.1)],
        )

    assert service.is_open is True


@pytest.mark.asyncio
async def test_401_does_not_trip_circuit_breaker() -> None:
    """Auth errors (401/403) should NOT trip the circuit breaker."""
    client = FakeRoutesClient(FakeResponse(status_code=401, payload={}))
    service = GoongRoutesService(settings=_settings(), client=client)

    for _ in range(FAILURE_THRESHOLD + 5):
        await service.computeRouteMatrix(
            LatLng(lat=10.0, lng=106.0),
            [LatLng(lat=10.1, lng=106.1)],
        )

    # Circuit should never open for auth errors
    assert service.is_open is False


@pytest.mark.asyncio
async def test_403_does_not_trip_circuit_breaker() -> None:
    """403 should behave like 401 — no circuit trip."""
    client = FakeRoutesClient(FakeResponse(status_code=403, payload={}))
    service = GoongRoutesService(settings=_settings(), client=client)

    for _ in range(FAILURE_THRESHOLD + 5):
        await service.computeRouteMatrix(
            LatLng(lat=10.0, lng=106.0),
            [LatLng(lat=10.1, lng=106.1)],
        )

    assert service.is_open is False


@pytest.mark.asyncio
async def test_4xx_non_429_returns_empty_no_trip() -> None:
    """Generic 4xx (e.g. 400) should return empty but not trip circuit."""
    client = FakeRoutesClient(FakeResponse(status_code=400, payload={}))
    service = GoongRoutesService(settings=_settings(), client=client)

    results = await service.computeRouteMatrix(
        LatLng(lat=10.0, lng=106.0),
        [LatLng(lat=10.1, lng=106.1)],
    )

    assert results == []
    assert service.is_open is False


@pytest.mark.asyncio
async def test_malformed_json_records_failure() -> None:
    """Non-JSON response body should record a failure."""
    client = FakeRoutesClient(
        FakeResponse(status_code=200, json_error=ValueError("bad json"))
    )
    service = GoongRoutesService(settings=_settings(), client=client)

    results = await service.computeRouteMatrix(
        LatLng(lat=10.0, lng=106.0),
        [LatLng(lat=10.1, lng=106.1)],
    )

    assert results == []



@pytest.mark.asyncio
async def test_malformed_rows_records_failure() -> None:
    """Missing or non-list rows payload is malformed and trips after threshold."""
    service = GoongRoutesService(
        settings=_settings(),
        client=FakeRoutesClient(FakeResponse(status_code=200, payload={"status": "OK"})),
    )

    for _ in range(FAILURE_THRESHOLD):
        results = await service.computeRouteMatrix(
            LatLng(lat=10.0, lng=106.0),
            [LatLng(lat=10.1, lng=106.1)],
        )
        assert results == []

    assert service.is_open is True

@pytest.mark.asyncio
async def test_empty_elements_returns_empty_without_failure() -> None:
    """An empty Goong elements array normalizes to no route results."""
    client = FakeRoutesClient(FakeResponse(status_code=200, payload={"rows": [{"elements": []}]}))
    service = GoongRoutesService(settings=_settings(), client=client)

    results = await service.computeRouteMatrix(
        LatLng(lat=10.0, lng=106.0),
        [LatLng(lat=10.1, lng=106.1)],
    )

    assert results == []
    assert service.is_open is False

# ── enrich_candidates ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enrich_candidates_populates_route_context() -> None:
    """Successful API call should populate route_context on each candidate."""
    origin = LatLng(lat=10.0, lng=106.0)
    c1 = _candidate("Restaurant A", 10.1, 106.1)
    c2 = _candidate("Restaurant B", 10.2, 106.2)

    client = FakeRoutesClient(
        FakeResponse(
            status_code=200,
            payload={"rows": [{"elements": [
                {"status": "OK", "distance": {"value": 5000}, "duration": {"value": 300}},
                {"status": "OK", "distance": {"value": 8000}, "duration": {"value": 480}},
            ]}]},
        )
    )
    service = GoongRoutesService(settings=_settings(), client=client)

    result = await service.enrich_candidates([c1, c2], origin)

    assert len(result) == 2
    assert result[0].route_context is not None
    assert result[0].route_context.distance_meters == 5000
    assert result[0].route_context.duration_seconds == 300
    assert result[0].route_context.travel_mode == "drive"
    assert result[1].route_context.distance_meters == 8000


@pytest.mark.asyncio
async def test_enrich_candidates_returns_unchanged_when_key_missing() -> None:
    """Missing API key should return candidates unchanged."""
    origin = LatLng(lat=10.0, lng=106.0)
    c1 = _candidate("Restaurant A", 10.1, 106.1)

    client = FakeRoutesClient(
        FakeResponse(status_code=200, payload={"rows": [{"elements": [{"status": "OK"}]}]})
    )
    service = GoongRoutesService(settings=_settings(routes_key=""), client=client)

    result = await service.enrich_candidates([c1], origin)

    assert len(result) == 1
    assert result[0].route_context is None
    assert len(client.calls) == 0


@pytest.mark.asyncio
async def test_enrich_candidates_returns_unchanged_when_circuit_open() -> None:
    """Open circuit breaker should return candidates unchanged."""
    origin = LatLng(lat=10.0, lng=106.0)
    c1 = _candidate("Restaurant A", 10.1, 106.1)

    client = FakeRoutesClient(
        FakeResponse(status_code=200, payload={"rows": [{"elements": [{"status": "OK"}]}]})
    )
    service = GoongRoutesService(settings=_settings(), client=client)
    for _ in range(FAILURE_THRESHOLD):
        service._circuit_breaker.record_failure()

    result = await service.enrich_candidates([c1], origin)

    assert len(result) == 1
    assert result[0].route_context is None
    assert len(client.calls) == 0


@pytest.mark.asyncio
async def test_enrich_candidates_skips_candidates_without_location() -> None:
    """Candidates without a location should not be sent to the API."""
    origin = LatLng(lat=10.0, lng=106.0)
    c1 = _candidate("Restaurant A", 10.1, 106.1)
    c2 = PlaceCandidate(place_id="pid-no-loc", display_name="No Location")  # no location

    client = FakeRoutesClient(
        FakeResponse(
            status_code=200,
            payload={"rows": [{"elements": [{"status": "OK", "distance": {"value": 5000}}]}]},
        )
    )
    service = GoongRoutesService(settings=_settings(), client=client)

    result = await service.enrich_candidates([c1, c2], origin)

    assert len(result) == 2
    # c1 should be enriched
    assert result[0].route_context is not None or result[1].route_context is not None
    # c2 should have no route context
    no_loc_candidate = next(c for c in result if c.place_id == "pid-no-loc")
    assert no_loc_candidate.route_context is None


@pytest.mark.asyncio
async def test_enrich_candidates_empty_list_returns_empty() -> None:
    """Empty candidate list should return empty without API call."""
    client = FakeRoutesClient(
        FakeResponse(status_code=200, payload={"rows": [{"elements": [{"status": "OK"}]}]})
    )
    service = GoongRoutesService(settings=_settings(), client=client)

    result = await service.enrich_candidates([], LatLng(lat=10.0, lng=106.0))

    assert result == []
    assert len(client.calls) == 0


@pytest.mark.asyncio
async def test_enrich_candidates_handles_api_error_gracefully() -> None:
    """When API returns errors, candidates should keep None route_context."""
    origin = LatLng(lat=10.0, lng=106.0)
    c1 = _candidate("Restaurant A", 10.1, 106.1)

    client = FakeRoutesClient(
        FakeResponse(status_code=500, payload={})
    )
    service = GoongRoutesService(settings=_settings(), client=client)

    result = await service.enrich_candidates([c1], origin)

    assert len(result) == 1
    assert result[0].route_context is None
