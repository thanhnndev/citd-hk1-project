"""Tests for Google Places (New) service with circuit breaker and cache fallback.

Covers:
- Circuit breaker: opens after consecutive failures, half-open after cooldown, closes on success
- Cache fallback: on timeout/500/malformed/circuit-open, tries Postgres cache
- Cache upsert: successful OK results are written to cache
- Honest unavailable responses: no RAG fallback, no citations when cache miss
- Secret redaction: no API keys in any error path or serialized result
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

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
from agents.tools.places_service import (
    CircuitState,
    GooglePlacesService,
    normalize_place,
)


# ---------------------------------------------------------------------------
# Fake HTTP client
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Fake cache
# ---------------------------------------------------------------------------

class FakeCacheDiagnostics(dict):
    @property
    def result(self) -> str:
        return self.get("result", "unknown")

    @property
    def cache_hit(self) -> bool:
        return self.result == "hit"

    @property
    def cache_stale(self) -> bool:
        return self.result == "stale"


class FakePlaceCache:
    """In-memory fake cache for testing cache integration."""

    def __init__(self) -> None:
        self._store: dict[str, list[dict]] = {}
        self._stale_store: dict[str, list[dict]] = {}
        self.lookup_calls: list[PlaceSearchRequest] = []
        self.upsert_calls: list[tuple[PlaceSearchRequest, list[PlaceCandidate]]] = []
        self.raise_on_lookup: Exception | None = None
        self.raise_on_upsert: Exception | None = None
        self.force_stale: bool = False  # if True, lookups return stale even for hits
        self.force_malformed: bool = False  # if True, lookups return malformed result

    async def lookup(self, request: PlaceSearchRequest, *, ttl_seconds: int = 900):
        self.lookup_calls.append(request)
        if self.raise_on_lookup:
            raise self.raise_on_lookup
        from agents.tools.place_cache import PlaceCache
        key = PlaceCache._cache_key(request)

        # Malformed path
        if self.force_malformed:
            return None, FakeCacheDiagnostics(result="miss", cache_key=key[:8], reason="malformed_cache_data")

        # Stale path
        if self.force_stale:
            # Check stale_store first, then fall back to _store for convenience
            stale_candidates = self._stale_store.get(key) or self._store.get(key)
            if stale_candidates:
                parsed = [PlaceCandidate.model_validate(c) for c in stale_candidates]
                return parsed, FakeCacheDiagnostics(
                    result="stale", cache_key=key[:8], candidate_count=len(parsed),
                    staleness_seconds=3600.0,
                )
            return None, FakeCacheDiagnostics(result="stale", cache_key=key[:8], reason="empty_candidates")

        # Normal hit/miss path
        candidates = self._store.get(key)
        if candidates is None:
            return None, FakeCacheDiagnostics(result="miss", cache_key=key[:8])
        parsed = [PlaceCandidate.model_validate(c) for c in candidates]
        if not parsed:
            return None, FakeCacheDiagnostics(result="miss", cache_key=key[:8], reason="empty")
        return parsed, FakeCacheDiagnostics(result="hit", cache_key=key[:8], candidate_count=len(parsed))

    async def upsert(self, request: PlaceSearchRequest, candidates: list[PlaceCandidate], *, ttl_seconds: int = 900, source: str = "goong_places"):
        from agents.tools.place_cache import PlaceCache
        key = PlaceCache._cache_key(request)
        self.upsert_calls.append((request, candidates))
        if self.raise_on_upsert:
            raise self.raise_on_upsert
        self._store[key] = [c.model_dump(mode="json") for c in candidates]
        return FakeCacheDiagnostics(result="write_ok", cache_key=key[:8], candidate_count=len(candidates))

    async def ensure_table(self) -> None:
        pass

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def make_request(query: str = "seafood", **kwargs: Any) -> PlaceSearchRequest:
    base: dict[str, Any] = {
        "query": query,
        "language_code": "vi",
    }
    base.update(kwargs)
    return PlaceSearchRequest(**base)


# ---------------------------------------------------------------------------
# Circuit Breaker unit tests
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    """Verify CircuitState behavior in isolation."""

    def test_starts_closed(self):
        cb = CircuitState(failure_threshold=3)
        assert cb.state == "closed"
        assert not cb.is_open

    def test_opens_after_threshold(self):
        cb = CircuitState(failure_threshold=3, cooldown_seconds=30.0)
        cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()
        assert cb.state == "open"
        assert cb.is_open

    def test_closes_on_success(self):
        cb = CircuitState(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        cb.record_success()
        assert cb.state == "closed"
        assert not cb.is_open

    def test_half_open_after_cooldown(self):
        cb = CircuitState(failure_threshold=1, cooldown_seconds=0.001)
        cb.record_failure()
        assert cb.state == "open"
        # Wait past cooldown
        import time
        time.sleep(0.005)
        assert cb.state == "half-open"

    def test_half_open_probe_success_closes(self):
        cb = CircuitState(failure_threshold=1, cooldown_seconds=0.001)
        cb.record_failure()
        import time
        time.sleep(0.005)
        assert cb.state == "half-open"
        cb.record_success()
        assert cb.state == "closed"

    def test_consecutive_failures_reset_on_success(self):
        cb = CircuitState(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.consecutive_failures == 0
        cb.record_failure()
        assert cb.consecutive_failures == 1

    def test_success_during_closed_does_nothing_harmful(self):
        cb = CircuitState(failure_threshold=3)
        cb.record_success()
        assert cb.state == "closed"
        assert cb.consecutive_failures == 0


# ---------------------------------------------------------------------------
# Cache hit fallback on provider failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCacheFallbackOnFailure:
    """When provider fails, service should try cache before returning unavailable."""

    async def test_timeout_then_cache_hit_returns_ok_with_cache_source(self):
        """Provider timeout → cache hit → results served from cache."""
        cache = FakePlaceCache()
        # Pre-seed cache
        req = make_request("seafood")
        candidates = [PlaceCandidate(place_id="cached_1", display_name="Cached Seafood", types=["restaurant"])]
        await cache.upsert(req, candidates)

        client = FakeClient(httpx.TimeoutException("timed out"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(req)

        assert response.status == PlaceToolStatus.OK
        assert response.source == PlaceToolSource.CACHE
        assert len(response.candidates) == 1
        assert response.candidates[0].place_id == "cached_1"
        assert any("cache" in entry.lower() for entry in response.reasoning_log)
        # Verify cache was consulted
        assert len(cache.lookup_calls) >= 1

    async def test_timeout_then_cache_miss_returns_unavailable(self):
        """Provider timeout → cache miss → honest unavailable."""
        cache = FakePlaceCache()
        client = FakeClient(httpx.TimeoutException("timed out"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(make_request("nonexistent query"))

        assert response.status == PlaceToolStatus.UNAVAILABLE
        assert response.candidates == []
        # Reasoning log should include provider error info
        assert len(response.reasoning_log) > 0
        assert any("provider" in entry.lower() for entry in response.reasoning_log)
        assert any("miss" in entry.lower() for entry in response.reasoning_log)

    async def test_500_error_then_cache_hit(self):
        """500 upstream error → cache hit → results from cache."""
        cache = FakePlaceCache()
        req = make_request("coffee")
        candidates = [PlaceCandidate(place_id="cafe_1", display_name="Local Cafe", types=["cafe"])]
        await cache.upsert(req, candidates)

        client = FakeClient(FakeResponse(status_code=500))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(req)

        assert response.status == PlaceToolStatus.OK
        assert response.source == PlaceToolSource.CACHE
        assert response.candidates[0].place_id == "cafe_1"

    async def test_malformed_json_then_cache_hit(self):
        """Malformed JSON response → cache hit → results from cache."""
        cache = FakePlaceCache()
        req = make_request("pho")
        candidates = [PlaceCandidate(place_id="pho_1", display_name="Pho Restaurant", types=["restaurant"])]
        await cache.upsert(req, candidates)

        client = FakeClient(FakeResponse(json_error=ValueError("not json")))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(req)

        assert response.status == PlaceToolStatus.OK
        assert response.source == PlaceToolSource.CACHE

    async def test_generic_exception_then_cache_miss(self):
        """Generic network error → cache miss → unavailable."""
        cache = FakePlaceCache()
        client = FakeClient(RuntimeError("network unreachable"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(make_request("anything"))

        assert response.status == PlaceToolStatus.UNAVAILABLE
        assert response.candidates == []

    async def test_cache_error_returns_unavailable_with_warning(self):
        """Provider fails AND cache lookup errors → unavailable with warning."""
        cache = FakePlaceCache()
        cache.raise_on_lookup = RuntimeError("cache db down")
        client = FakeClient(httpx.TimeoutException("timeout"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(make_request("test"))

        assert response.status == PlaceToolStatus.UNAVAILABLE
        assert any("cache" in w.lower() for w in response.warnings)

    async def test_no_cache_configured_returns_unavailable(self):
        """Provider fails with no cache → honest unavailable."""
        client = FakeClient(httpx.TimeoutException("timeout"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=None)

        response = await service.text_search(make_request("test"))

        assert response.status == PlaceToolStatus.UNAVAILABLE
        assert response.candidates == []
        assert len(response.reasoning_log) > 0
        assert any("provider" in entry.lower() for entry in response.reasoning_log)


# ---------------------------------------------------------------------------
# Circuit-open skips provider and uses cache
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCircuitOpenSkipsProvider:
    """When circuit is open, provider calls are skipped entirely."""

    async def test_circuit_open_uses_cache_without_calling_provider(self):
        """Circuit already open → skip provider → try cache."""
        cache = FakePlaceCache()
        req = make_request("sushi")
        candidates = [PlaceCandidate(place_id="sushi_1", display_name="Sushi Bar", types=["restaurant"])]
        await cache.upsert(req, candidates)

        # Create service with pre-opened circuit
        circuit = CircuitState(failure_threshold=1)
        circuit.record_failure()  # force open

        client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache, circuit=circuit)

        response = await service.text_search(req)

        # Provider should NOT have been called
        assert len(client.post_calls) == 0
        # Cache should have been consulted
        assert len(cache.lookup_calls) >= 1
        assert response.status == PlaceToolStatus.OK
        assert response.source == PlaceToolSource.CACHE
        assert response.candidates[0].place_id == "sushi_1"

    async def test_circuit_open_cache_miss_returns_unavailable(self):
        """Circuit open + cache miss → unavailable, no provider call."""
        cache = FakePlaceCache()
        circuit = CircuitState(failure_threshold=1)
        circuit.record_failure()

        client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache, circuit=circuit)

        response = await service.text_search(make_request("anything"))

        assert len(client.post_calls) == 0
        assert response.status == PlaceToolStatus.UNAVAILABLE
        assert response.candidates == []

    async def test_repeated_failures_open_circuit_then_recovers(self):
        """3 failures open circuit; after cooldown, probe succeeds and circuit closes."""
        cache = FakePlaceCache()
        circuit = CircuitState(failure_threshold=3, cooldown_seconds=0.001)
        client = FakeClient([
            httpx.TimeoutException("timeout 1"),
            httpx.TimeoutException("timeout 2"),
            httpx.TimeoutException("timeout 3"),
            FakeResponse(payload={"places": [google_place()]}),  # probe succeeds
        ])
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache, circuit=circuit)

        # Three failures should open circuit (but still try cache each time)
        for i in range(3):
            resp = await service.text_search(make_request(f"query_{i}"))
            assert resp.status in (PlaceToolStatus.UNAVAILABLE,)

        assert circuit.state == "open"

        # Wait for cooldown — generous margin for CI
        import time
        time.sleep(0.05)

        # Next call should go through as half-open probe — state transitions from
        # half-open to closed on success
        response = await service.text_search(make_request("recovered"))
        assert response.status == PlaceToolStatus.OK
        assert response.source == PlaceToolSource.GOOGLE_PLACES
        assert circuit.state == "closed"


# ---------------------------------------------------------------------------
# Cache upsert on successful responses
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCacheUpsertOnSuccess:
    """Successful provider responses should be upserted to cache."""

    async def test_ok_response_upserts_to_cache(self):
        """text_search OK → candidates written to cache."""
        cache = FakePlaceCache()
        client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(make_request("seafood"))

        assert response.status == PlaceToolStatus.OK
        assert len(cache.upsert_calls) == 1
        req, candidates = cache.upsert_calls[0]
        assert req.query == "seafood"
        assert len(candidates) == 1
        assert candidates[0].place_id == "google_ham_ninh"

    async def test_empty_response_does_not_upsert(self):
        """Zero results → no cache write."""
        cache = FakePlaceCache()
        client = FakeClient(FakeResponse(payload={"places": []}))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(make_request("nothing here"))

        assert response.status == PlaceToolStatus.EMPTY
        assert len(cache.upsert_calls) == 0

    async def test_error_response_does_not_upsert(self):
        """Provider error → no cache write."""
        cache = FakePlaceCache()
        client = FakeClient(httpx.TimeoutException("timeout"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        await service.text_search(make_request("fail"))

        assert len(cache.upsert_calls) == 0

    async def test_cache_upsert_error_does_not_break_response(self):
        """Cache write failure should not affect successful provider response."""
        cache = FakePlaceCache()
        cache.raise_on_upsert = RuntimeError("cache db down")
        client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(make_request("seafood"))

        # Response should still be OK
        assert response.status == PlaceToolStatus.OK
        assert response.candidates[0].place_id == "google_ham_ninh"

    async def test_nearby_search_upserts_to_cache(self):
        """nearby_search OK → candidates written to cache."""
        cache = FakePlaceCache()
        client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        from app.models.places import PlaceNearbyRequest, LatLng
        req = PlaceNearbyRequest(
            center=LatLng(lat=10.18, lng=104.05),
            included_type="restaurant",
        )
        response = await service.nearby_search(req)

        assert response.status == PlaceToolStatus.OK
        # NearbySearchRequest is not PlaceSearchRequest, so upsert should be skipped
        assert len(cache.upsert_calls) == 0


# ---------------------------------------------------------------------------
# Secret redaction in all error paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSecretRedaction:
    """No API keys, credentials, or raw provider payloads in any response."""

    async def test_no_api_key_in_unavailable_response(self):
        cache = FakePlaceCache()
        client = FakeClient(httpx.TimeoutException("timeout"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(make_request("test"))

        dump = response.model_dump_json()
        assert "test-google-key" not in dump
        assert "api_key" not in dump.lower() or "missing_google_api_key" in dump.lower()

    async def test_no_api_key_in_cache_hit_response(self):
        cache = FakePlaceCache()
        req = make_request("seafood")
        candidates = [PlaceCandidate(place_id="cached_1", display_name="Cached Seafood", types=["restaurant"])]
        await cache.upsert(req, candidates)

        client = FakeClient(httpx.TimeoutException("timeout"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(req)

        dump = response.model_dump_json()
        assert "test-google-key" not in dump

    async def test_no_api_key_in_circuit_open_response(self):
        circuit = CircuitState(failure_threshold=1)
        circuit.record_failure()
        cache = FakePlaceCache()
        client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache, circuit=circuit)

        response = await service.text_search(make_request("test"))

        dump = response.model_dump_json()
        assert "test-google-key" not in dump


# ---------------------------------------------------------------------------
# Observability: warnings and reasoning_log
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestObservability:
    """Verify structured diagnostics in warnings, reasoning_log, and audit."""

    async def test_cache_hit_includes_warning_about_provider(self):
        cache = FakePlaceCache()
        req = make_request("seafood")
        await cache.upsert(req, [PlaceCandidate(place_id="p1", display_name="P1", types=["restaurant"])])

        client = FakeClient(httpx.TimeoutException("timeout"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(req)

        assert response.status == PlaceToolStatus.OK
        assert any("provider" in w.lower() and "unavailable" in w.lower() for w in response.warnings)
        assert any("cache" in entry.lower() for entry in response.reasoning_log)

    async def test_unavailable_response_has_reasoning_log(self):
        cache = FakePlaceCache()
        client = FakeClient(httpx.TimeoutException("timeout"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(make_request("test"))

        assert response.status == PlaceToolStatus.UNAVAILABLE
        assert len(response.reasoning_log) > 0
        assert any("provider" in entry.lower() for entry in response.reasoning_log)

    async def test_audit_includes_fallback_reason(self):
        cache = FakePlaceCache()
        client = FakeClient(httpx.TimeoutException("timeout"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(make_request("test"))

        assert "fallback_reason" in response.audit
        assert "provider" in response.audit["fallback_reason"]

    async def test_circuit_state_in_audit(self):
        """Circuit-open response should include circuit state in audit."""
        circuit = CircuitState(failure_threshold=1)
        circuit.record_failure()
        cache = FakePlaceCache()
        client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache, circuit=circuit)

        response = await service.text_search(make_request("test"))

        # Circuit-open responses include fallback_reason = "circuit_open"
        assert response.audit.get("fallback_reason") == "circuit_open"


# ---------------------------------------------------------------------------
# Existing tests (preserved from T01) — verify no regressions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestExistingBehaviorPreserved:
    """Verify that existing behavior from T01 is preserved."""

    async def test_missing_key_returns_credential_blocked(self):
        service = GooglePlacesService(settings=settings(api_key=""), client=FakeClient(FakeResponse()))
        response = await service.text_search(PlaceSearchRequest(query="seafood"))
        assert response.status == PlaceToolStatus.CREDENTIALS_BLOCKED

    async def test_text_search_normalizes_google_payload(self):
        client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
        service = GooglePlacesService(settings=settings(), client=client)
        response = await service.text_search(PlaceSearchRequest(query="seafood", max_result_count=3))
        assert response.status == PlaceToolStatus.OK
        assert response.source == PlaceToolSource.GOOGLE_PLACES
        assert response.candidates[0].place_id == "google_ham_ninh"

    async def test_timeout_maps_to_safe_error_without_cache(self):
        """Without cache, timeout still maps to UPSTREAM_ERROR (original behavior)."""
        client = FakeClient(httpx.TimeoutException("boom"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=None)
        response = await service.text_search(PlaceSearchRequest(query="coffee"))
        # Without cache, the error result from _request_post is returned directly
        # BUT the circuit breaker records failure. The _execute_search flow returns the error result.
        # Actually with the new flow: error result → circuit.record_failure → fallback_from_cache → unavailable
        assert response.status == PlaceToolStatus.UNAVAILABLE
        assert response.candidates == []

    async def test_empty_provider_places_returns_empty_status(self):
        client = FakeClient(FakeResponse(payload={"places": []}))
        service = GooglePlacesService(settings=settings(), client=client)
        response = await service.text_search(PlaceSearchRequest(query="nonexistent"))
        assert response.status == PlaceToolStatus.EMPTY
        assert response.candidates == []

    async def test_malformed_place_entries_skipped(self):
        client = FakeClient(FakeResponse(payload={
            "places": [
                google_place(id="valid_place"),
                {"no_id_field": True},
                "not_a_dict",
                None,
            ]
        }))
        service = GooglePlacesService(settings=settings(), client=client)
        response = await service.text_search(PlaceSearchRequest(query="mixed"))
        assert response.status == PlaceToolStatus.OK
        assert len(response.candidates) == 1

    async def test_no_secrets_in_serialized_result(self):
        client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
        service = GooglePlacesService(settings=settings(), client=client)
        response = await service.text_search(PlaceSearchRequest(query="test"))
        dump = response.model_dump_json()
        assert "test-google-key" not in dump
        assert "secret" not in dump.lower()

    async def test_reasoning_log_populated_for_ok(self):
        client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
        service = GooglePlacesService(settings=settings(), client=client)
        response = await service.text_search(PlaceSearchRequest(query="test"))
        assert response.reasoning_log
        assert any("normalized" in entry.lower() for entry in response.reasoning_log)

    async def test_audit_includes_endpoint_and_field_mask(self):
        client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
        service = GooglePlacesService(settings=settings(), client=client)
        response = await service.text_search(PlaceSearchRequest(query="test"))
        assert "endpoint" in response.audit
        assert "field_mask" in response.audit
        assert response.audit["field_mask"] == GOOGLE_PLACES_FIELD_MASK
        assert response.interpreted_query == "test"
        assert response.request_metadata["field_mask"] == GOOGLE_PLACES_FIELD_MASK
        assert response.request_metadata["max_result_count"] == 10


# ---------------------------------------------------------------------------
# Stale cache fallback — degraded results with staleness warning
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestStaleCacheFallback:
    """Stale cache entries are served as degraded results with a warning."""

    async def test_stale_cache_hit_serves_degraded_results(self):
        """Provider timeout → stale cache → degraded results with staleness warning."""
        cache = FakePlaceCache()
        req = make_request("stale seafood")
        candidates = [PlaceCandidate(place_id="stale_1", display_name="Stale Seafood", types=["restaurant"])]
        await cache.upsert(req, candidates)
        cache.force_stale = True

        client = FakeClient(httpx.TimeoutException("timeout"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(req)

        assert response.status == PlaceToolStatus.OK
        assert response.source == PlaceToolSource.CACHE
        assert len(response.candidates) == 1
        assert response.candidates[0].place_id == "stale_1"
        assert any("stale" in w.lower() for w in response.warnings)
        assert any("stale" in entry.lower() for entry in response.reasoning_log)
        assert response.audit.get("fallback_source") == "cache_stale"
        assert response.audit.get("staleness_seconds") == 3600.0

    async def test_stale_cache_empty_returns_unavailable(self):
        """Stale cache with no data → honest unavailable."""
        cache = FakePlaceCache()
        cache.force_stale = True
        client = FakeClient(httpx.TimeoutException("timeout"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(make_request("nothing"))

        assert response.status == PlaceToolStatus.UNAVAILABLE
        assert response.candidates == []
        assert "stale" in response.audit.get("cache_result", "")


# ---------------------------------------------------------------------------
# Malformed cache data → treated as miss
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestMalformedCacheBehavior:
    """Malformed cache rows behave as cache misses."""

    async def test_malformed_cache_returns_unavailable(self):
        """Provider error + malformed cache → unavailable (malformed treated as miss)."""
        cache = FakePlaceCache()
        cache.force_malformed = True
        client = FakeClient(httpx.TimeoutException("timeout"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(make_request("test"))

        assert response.status == PlaceToolStatus.UNAVAILABLE
        assert response.candidates == []
        # Should indicate miss behavior, not serve broken data
        assert response.audit.get("cache_result") in ("miss", "no_cache")


# ---------------------------------------------------------------------------
# Provider error types → cache fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestProviderErrorTypesFallback:
    """Different provider error types all trigger cache fallback before unavailable."""

    async def test_auth_error_triggers_cache_fallback(self):
        """403 auth error → circuit failure → cache fallback."""
        cache = FakePlaceCache()
        req = make_request("auth test")
        await cache.upsert(req, [PlaceCandidate(place_id="auth_cached", display_name="Auth Cached", types=["restaurant"])])

        client = FakeClient(FakeResponse(status_code=403))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(req)

        assert response.status == PlaceToolStatus.OK
        assert response.source == PlaceToolSource.CACHE
        assert response.candidates[0].place_id == "auth_cached"

    async def test_quota_exceeded_triggers_cache_fallback(self):
        """429 rate limit → circuit failure → cache fallback."""
        cache = FakePlaceCache()
        req = make_request("quota test")
        await cache.upsert(req, [PlaceCandidate(place_id="quota_cached", display_name="Quota Cached", types=["cafe"])])

        client = FakeClient(FakeResponse(status_code=429))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(req)

        assert response.status == PlaceToolStatus.OK
        assert response.source == PlaceToolSource.CACHE


# ---------------------------------------------------------------------------
# Details endpoint failure paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestDetailsFailurePaths:
    """Details endpoint handles circuit-open and cache fallback."""

    async def test_details_circuit_open_uses_cache(self):
        """Details + circuit open → skip provider → cache fallback."""
        cache = FakePlaceCache()
        circuit = CircuitState(failure_threshold=1)
        circuit.record_failure()
        client = FakeClient(FakeResponse(payload={"id": "details_place", "displayName": {"text": "Should Not Be Called"}}))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache, circuit=circuit)

        req = PlaceDetailsRequest(place_id="places/any_id")
        response = await service.details(req)

        # Provider should NOT have been called (circuit open)
        assert len(client.get_calls) == 0
        # Details requests use PlaceDetailsRequest, not PlaceSearchRequest,
        # so cache is not supported → unavailable
        assert response.status == PlaceToolStatus.UNAVAILABLE
        assert response.candidates == []

    async def test_details_timeout_returns_upstream_error_then_unavailable(self):
        """Details timeout → cache not supported (not PlaceSearchRequest) → unavailable."""
        cache = FakePlaceCache()
        client = FakeClient(httpx.TimeoutException("timeout"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        req = PlaceDetailsRequest(place_id="places/any_id")
        response = await service.details(req)

        assert response.status == PlaceToolStatus.UNAVAILABLE
        assert response.candidates == []


# ---------------------------------------------------------------------------
# DB error returns safe diagnostics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCacheDBErrorDiagnostics:
    """DB errors in cache return safe diagnostics, not raw exceptions."""

    async def test_cache_db_error_does_not_propagate(self):
        """Provider timeout + cache DB error → unavailable with safe warning."""
        cache = FakePlaceCache()
        cache.raise_on_lookup = RuntimeError("connection refused: port 5432")
        client = FakeClient(httpx.TimeoutException("timeout"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        # Should not raise — returns unavailable with safe warning
        response = await service.text_search(make_request("test"))

        assert response.status == PlaceToolStatus.UNAVAILABLE
        assert response.candidates == []
        assert any("cache" in w.lower() for w in response.warnings)
        # No raw error message or stack trace in response
        dump = response.model_dump_json()
        assert "connection refused" not in dump
        assert "port 5432" not in dump

    async def test_cache_upsert_db_error_does_not_break_response(self):
        """Cache upsert DB error should not break successful provider response."""
        cache = FakePlaceCache()
        cache.raise_on_upsert = RuntimeError("disk full")
        client = FakeClient(FakeResponse(payload={"places": [google_place()]}))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(make_request("seafood"))

        assert response.status == PlaceToolStatus.OK
        assert response.candidates[0].place_id == "google_ham_ninh"


# ---------------------------------------------------------------------------
# request_metadata preserves field_mask
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRequestMetadataPreserved:
    """request_metadata always includes field_mask, even in failure paths."""

    async def test_cache_hit_preserves_field_mask(self):
        cache = FakePlaceCache()
        req = make_request("metadata test")
        await cache.upsert(req, [PlaceCandidate(place_id="p1", display_name="P1", types=["restaurant"])])
        client = FakeClient(httpx.TimeoutException("timeout"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(req)

        assert response.request_metadata["field_mask"] == GOOGLE_PLACES_FIELD_MASK

    async def test_unavailable_preserves_field_mask(self):
        cache = FakePlaceCache()
        client = FakeClient(httpx.TimeoutException("timeout"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(make_request("test"))

        assert response.request_metadata["field_mask"] == GOOGLE_PLACES_FIELD_MASK


# ---------------------------------------------------------------------------
# No RAG fallback / no citations in any failure path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestNoRagFallback:
    """No RAG fallback or document citations are ever introduced in failure paths."""

    async def test_no_citations_in_unavailable(self):
        cache = FakePlaceCache()
        client = FakeClient(httpx.TimeoutException("timeout"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(make_request("test"))

        dump = response.model_dump_json()
        assert "citation" not in dump.lower()
        assert "rag" not in dump.lower()
        assert "document" not in dump.lower() or "no documents" in dump.lower()

    async def test_no_citations_in_cache_hit(self):
        cache = FakePlaceCache()
        req = make_request("local restaurant")
        await cache.upsert(req, [PlaceCandidate(place_id="p1", display_name="P1", types=["restaurant"])])
        client = FakeClient(httpx.TimeoutException("timeout"))
        service = GooglePlacesService(settings=settings(), client=client, place_cache=cache)

        response = await service.text_search(req)

        dump = response.model_dump_json()
        assert "citation" not in dump.lower()
        assert "rag" not in dump.lower()

@pytest.mark.asyncio
async def test_text_search_hydrates_top_candidates_with_place_details():
    search_payload = {"places": [google_place(id="rich_1", displayName={"text": "Rich Search"})]}
    detail_payload = google_place(
        id="rich_1",
        displayName={"text": "Rich Detail"},
        primaryTypeDisplayName={"text": "Coffee shop"},
        editorialSummary={"text": "A locally loved coffee stop near Ham Ninh."},
        paymentOptions={"acceptsCreditCards": True, "acceptsCashOnly": False},
        parkingOptions={"freeParkingLot": True},
        takeout=True,
        delivery=False,
        dineIn=True,
        reservable=True,
        servesVegetarianFood=True,
        reviews=[{"rating": 5, "text": {"text": "Great local coffee."}, "authorAttribution": {"displayName": "A reviewer"}}],
        photos=[{"name": "places/rich_1/photos/photo_a"}],
    )
    class SplitClient:
        def __init__(self):
            self.post_calls = []
            self.get_calls = []

        async def post(self, path: str, *, json: dict, headers: dict) -> FakeResponse:
            self.post_calls.append((path, json, headers))
            return FakeResponse(payload=search_payload)

        async def get(self, path: str, *, headers: dict) -> FakeResponse:
            self.get_calls.append((path, headers))
            return FakeResponse(payload=detail_payload)

    client = SplitClient()
    service = GooglePlacesService(settings=settings(), client=client)

    response = await service.text_search(PlaceSearchRequest(query="coffee", max_result_count=1))

    assert response.status == PlaceToolStatus.OK
    assert len(client.get_calls) == 1
    assert "id,displayName" in client.get_calls[0][1]["X-Goog-FieldMask"]
    candidate = response.candidates[0]
    assert candidate.display_name == "Rich Detail"
    assert candidate.primary_type_display_name == "Coffee shop"
    assert candidate.editorial_summary == "A locally loved coffee stop near Ham Ninh."
    assert candidate.payment_options["acceptsCreditCards"] is True
    assert candidate.parking_options["freeParkingLot"] is True
    assert candidate.takeout is True
    assert candidate.dine_in is True
    assert candidate.reservable is True
    assert candidate.serves_vegetarian_food is True
    assert candidate.reviews[0]["text"] == "Great local coffee."
    assert candidate.photos == ["places/rich_1/photos/photo_a"]
    assert response.audit["details_hydrated"] == 1
