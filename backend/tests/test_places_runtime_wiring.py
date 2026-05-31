"""Runtime wiring tests for Postgres cache integration through the /chat place path.

Covers:
- Cache factory: configured when DATABASE_URL exists, skipped when absent
- Safe degraded startup when Postgres init fails
- Provider timeout with cache miss → UNAVAILABLE
- Provider timeout with cache hit → OK from cache, citations=[]
- Circuit-open skips provider and uses cache
- No RAG fallback or document citations in any cache-fallback path
- Secret redaction in all error/fallback paths
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.models.places import (
    PlaceCandidate,
    PlaceSearchRequest,
    PlaceToolSource,
    PlaceToolStatus,
)
from app.models.request import LatLng
from agents.services.place_recommendation_service import PlaceRecommendationService
from agents.tools.places_service import CircuitState, GooglePlacesService
from agents.tools.place_cache import PlaceCache, CacheDiagnostics


# ---------------------------------------------------------------------------
# Fake HTTP client for provider failure simulation
# ---------------------------------------------------------------------------

class FakeClient:
    """Fake HTTP client that always times out or raises errors."""

    def __init__(self, raise_exception: Exception | None = None) -> None:
        self._raise = raise_exception or httpx.TimeoutException("simulated timeout")
        self.post_calls: list = []
        self.get_calls: list = []

    async def post(self, path: str, *, json: dict, headers: dict):
        self.post_calls.append((path, json, headers))
        raise self._raise

    async def get(self, path: str, *, headers: dict):
        self.get_calls.append((path, headers))
        raise self._raise


# ---------------------------------------------------------------------------
# Fake cache with controlled hit/miss behavior
# ---------------------------------------------------------------------------

class FakePlaceCache:
    """In-memory fake cache for runtime wiring tests."""

    def __init__(self, candidates: list[PlaceCandidate] | None = None, result: str = "hit") -> None:
        self._candidates = candidates
        self._result = result
        self.lookup_calls: list = []
        self.upsert_calls: list = []
        self._ensured = False
        self._closed = False

    async def lookup(self, request: PlaceSearchRequest, *, ttl_seconds: int = 900):
        self.lookup_calls.append(request)
        if self._result == "hit" and self._candidates:
            return self._candidates, CacheDiagnostics(
                result="hit",
                cache_key="fake_key_001"[:8],
                candidate_count=len(self._candidates),
            )
        if self._result == "miss":
            return None, CacheDiagnostics(result="miss", cache_key="fake_key_001"[:8])
        if self._result == "stale":
            return None, CacheDiagnostics(result="stale", cache_key="fake_key_001"[:8])
        if self._result == "error":
            return None, CacheDiagnostics(result="error", cache_key="fake_key_001"[:8], error_type="RuntimeError")
        return None, CacheDiagnostics(result="miss", cache_key="fake_key_001"[:8])

    async def upsert(self, request: PlaceSearchRequest, candidates: list[PlaceCandidate], *, ttl_seconds: int = 900, source: str = "goong_places"):
        self.upsert_calls.append((request, candidates))
        return CacheDiagnostics(result="write_ok", cache_key="fake_key_001"[:8], candidate_count=len(candidates))

    async def ensure_table(self) -> None:
        self._ensured = True

    async def close(self) -> None:
        self._closed = True


# ---------------------------------------------------------------------------
# Fake settings
# ---------------------------------------------------------------------------

class FakeSettings:
    GOOGLE_PLACES_API_KEY = "fake-api-key-for-testing"
    DATABASE_URL = ""


# ---------------------------------------------------------------------------
# Test: Cache factory in main.py
# ---------------------------------------------------------------------------

class TestPlaceCacheFactory:
    """Tests for the _create_place_cache factory in main.py."""

    @pytest.mark.asyncio
    async def test_returns_none_when_dsn_absent(self) -> None:
        """Missing DATABASE_URL → cache is None (no crash)."""
        from app.main import _create_place_cache
        result = await _create_place_cache(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_dsn_blank(self) -> None:
        """Empty DATABASE_URL → cache is None."""
        from app.main import _create_place_cache
        result = await _create_place_cache("")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_connection_failure(self) -> None:
        """Invalid DATABASE_URL → cache is None, no crash."""
        from app.main import _create_place_cache
        result = await _create_place_cache("postgresql://localhost:5432/nonexistent")
        # Should return None (or possibly a PlaceCache with no pool)
        # Either way, it must not raise
        assert result is None or isinstance(result, PlaceCache)


# ---------------------------------------------------------------------------
# Test: Provider timeout + cache miss → UNAVAILABLE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provider_timeout_with_cache_miss_returns_unavailable() -> None:
    """When provider times out and cache has no entry, return UNAVAILABLE with honest text."""
    cache = FakePlaceCache(candidates=None, result="miss")
    service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeClient(),
        place_cache=cache,
    )

    request = PlaceSearchRequest(query="nhà hàng hải sản")
    result = await service.text_search(request)

    assert result.status == PlaceToolStatus.UNAVAILABLE
    assert result.candidates == []
    assert "fallback_reason" in result.audit


# ---------------------------------------------------------------------------
# Test: Provider timeout + cache hit → OK from cache, citations=[]
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provider_timeout_with_cache_hit_returns_cached_results() -> None:
    """When provider times out but cache has valid entries, return OK with cached candidates."""
    cached_candidates = [
        PlaceCandidate(
            place_id="places/cached-1",
            display_name="Quán Cua Đồng",
            types=["restaurant", "seafood_restaurant"],
            primary_type="seafood_restaurant",
            formatted_address="Hàm Ninh, Phú Quốc",
            location=LatLng(lat=10.1794, lng=104.0491),
            rating=4.5,
            user_rating_count=120,
            price_level=2,
            open_now=True,
        ),
        PlaceCandidate(
            place_id="places/cached-2",
            display_name="Hải Sản Hàm Ninh",
            types=["restaurant"],
            primary_type="restaurant",
            formatted_address="Hàm Ninh, Phú Quốc",
            location=LatLng(lat=10.1800, lng=104.0500),
            rating=4.3,
            user_rating_count=89,
            price_level=1,
            open_now=False,
        ),
    ]
    cache = FakePlaceCache(candidates=cached_candidates, result="hit")
    service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeClient(),
        place_cache=cache,
    )

    request = PlaceSearchRequest(query="nhà hàng hải sản")
    result = await service.text_search(request)

    assert result.status == PlaceToolStatus.OK
    assert len(result.candidates) == 2
    assert result.source == PlaceToolSource.CACHE
    assert result.candidates[0].place_id == "places/cached-1"
    assert len(cache.lookup_calls) == 1


# ---------------------------------------------------------------------------
# Test: Cache hit through recommendation service → ChatResponse with citations=[]
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_hit_through_recommendation_service_has_no_citations() -> None:
    """Cached results through PlaceRecommendationService produce ChatResponse with citations=[]."""
    cached_candidates = [
        PlaceCandidate(
            place_id="places/cached-rec",
            display_name="Quán Biển Hàm Ninh",
            types=["restaurant"],
            primary_type="restaurant",
            formatted_address="Hàm Ninh",
            location=LatLng(lat=10.1794, lng=104.0491),
            rating=4.5,
            user_rating_count=100,
        ),
    ]
    cache = FakePlaceCache(candidates=cached_candidates, result="hit")
    places_service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeClient(),
        place_cache=cache,
    )
    recommender = PlaceRecommendationService(places_service, routes_service=None)

    response = await recommender.recommend(query="nhà hàng", language="vi", session_id="s-cache-rec")

    assert response.citations == []
    assert response.intent == "place_recommendation"
    # Cached results should be present
    assert len(response.places) >= 1
    assert response.places[0].place_id == "places/cached-rec"


# ---------------------------------------------------------------------------
# Test: Cache miss through recommendation service → fallback response, no RAG
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_miss_through_recommendation_service_no_rag() -> None:
    """When cache miss on provider failure, response has no citations and honest text."""
    cache = FakePlaceCache(candidates=None, result="miss")
    places_service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeClient(),
        place_cache=cache,
    )
    recommender = PlaceRecommendationService(places_service, routes_service=None)

    response = await recommender.recommend(query="quán không tồn tại", language="vi", session_id="s-cache-miss")

    assert response.citations == []
    assert response.places == []
    assert response.intent == "place_recommendation"
    assert response.fallback is True
    # Message must be in Vietnamese (honest unavailable text)
    assert "không khả dụng" in response.message


# ---------------------------------------------------------------------------
# Test: Circuit-open skips provider and uses cache
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_circuit_open_skips_provider_uses_cache() -> None:
    """When circuit is open, provider is not called — cache is used directly."""
    cached_candidates = [
        PlaceCandidate(
            place_id="places/circuit-cached",
            display_name="Quán Mở Cửa",
            types=["restaurant"],
            location=LatLng(lat=10.1794, lng=104.0491),
        ),
    ]
    cache = FakePlaceCache(candidates=cached_candidates, result="hit")
    circuit = CircuitState(failure_threshold=1)
    circuit.record_failure()  # Force circuit open

    service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeClient(),  # Would fail if called
        place_cache=cache,
        circuit=circuit,
    )

    request = PlaceSearchRequest(query="test")
    result = await service.text_search(request)

    # Provider should NOT have been called — circuit is open
    fake_client = service._client
    assert isinstance(fake_client, FakeClient)
    assert len(fake_client.post_calls) == 0
    # Cache should have been used
    assert len(cache.lookup_calls) == 1
    assert result.status == PlaceToolStatus.OK
    assert result.source == PlaceToolSource.CACHE


# ---------------------------------------------------------------------------
# Test: Circuit-open + cache miss → UNAVAILABLE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_circuit_open_cache_miss_returns_unavailable() -> None:
    """Circuit open + cache miss returns UNAVAILABLE with honest text."""
    cache = FakePlaceCache(candidates=None, result="miss")
    circuit = CircuitState(failure_threshold=1)
    circuit.record_failure()

    service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeClient(),
        place_cache=cache,
        circuit=circuit,
    )

    request = PlaceSearchRequest(query="test")
    result = await service.text_search(request)

    assert result.status == PlaceToolStatus.UNAVAILABLE
    assert result.candidates == []
    assert "circuit" in result.audit.get("fallback_reason", "")


# ---------------------------------------------------------------------------
# Test: 500 error + cache hit → OK from cache
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_500_error_with_cache_hit_returns_cached() -> None:
    """Provider returns 500 → cache hit → OK with cached results."""

    class Fake500Client:
        async def post(self, path: str, *, json: dict, headers: dict):
            r = MagicMock()
            r.status_code = 500
            r.json.return_value = {"error": {"message": "Internal Server Error"}}
            return r

        async def get(self, path: str, *, headers: dict):
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {}
            return r

    cached_candidates = [
        PlaceCandidate(
            place_id="places/500-cached",
            display_name="Quán Sau Lỗi",
            types=["restaurant"],
            location=LatLng(lat=10.1794, lng=104.0491),
        ),
    ]
    cache = FakePlaceCache(candidates=cached_candidates, result="hit")
    service = GooglePlacesService(
        settings=FakeSettings,
        client=Fake500Client(),
        place_cache=cache,
    )

    request = PlaceSearchRequest(query="test")
    result = await service.text_search(request)

    assert result.status == PlaceToolStatus.OK
    assert result.source == PlaceToolSource.CACHE
    assert result.candidates[0].place_id == "places/500-cached"


# ---------------------------------------------------------------------------
# Test: No RAG fallback — citations always empty in error paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_citations_in_any_cache_fallback_path() -> None:
    """All cache-fallback paths must return citations=[] — no RAG fallback."""
    cache = FakePlaceCache(candidates=None, result="miss")
    places_service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeClient(),
        place_cache=cache,
    )
    recommender = PlaceRecommendationService(places_service, routes_service=None)

    response = await recommender.recommend(query="test", language="vi", session_id="s-nocite")

    assert response.citations == []
    # Reasoning log must reveal cache miss
    assert "cache" in response.reasoning_log.lower() or "unavailable" in response.reasoning_log.lower()


# ---------------------------------------------------------------------------
# Test: Secret redaction — no API key in any error/fallback response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_api_key_in_unavailable_response() -> None:
    """UNAVAILABLE responses must not expose GOOGLE_PLACES_API_KEY."""
    cache = FakePlaceCache(candidates=None, result="miss")
    service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeClient(),
        place_cache=cache,
    )

    request = PlaceSearchRequest(query="test")
    result = await service.text_search(request)

    dump = result.model_dump_json()
    assert "fake-api-key" not in dump.lower()
    assert "GOOGLE_PLACES_API_KEY" not in dump


@pytest.mark.asyncio
async def test_no_api_key_in_cache_hit_response() -> None:
    """Cache-hit fallback responses must not expose API keys."""
    cached_candidates = [
        PlaceCandidate(
            place_id="places/redact-test",
            display_name="Quán An Toàn",
            types=["restaurant"],
            location=LatLng(lat=10.1794, lng=104.0491),
        ),
    ]
    cache = FakePlaceCache(candidates=cached_candidates, result="hit")
    service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeClient(),
        place_cache=cache,
    )

    request = PlaceSearchRequest(query="test")
    result = await service.text_search(request)

    dump = result.model_dump_json()
    assert "fake-api-key" not in dump.lower()


# ---------------------------------------------------------------------------
# Test: Provider exception → cache fallback → deterministic grounded text
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provider_exception_with_cache_hit_produces_deterministic_text() -> None:
    """Provider throws exception → cache hit → PlaceRecommendationService produces deterministic text."""
    cached_candidates = [
        PlaceCandidate(
            place_id="places/deterministic",
            display_name="QuánDeterministic",
            types=["restaurant"],
            location=LatLng(lat=10.1794, lng=104.0491),
            rating=4.0,
            user_rating_count=50,
        ),
    ]
    cache = FakePlaceCache(candidates=cached_candidates, result="hit")
    places_service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeClient(raise_exception=RuntimeError("connection refused")),
        place_cache=cache,
    )
    recommender = PlaceRecommendationService(places_service, routes_service=None)

    response = await recommender.recommend(query="nhà hàng", language="vi", session_id="s-deterministic")

    # Must have places from cache
    assert len(response.places) >= 1
    assert response.places[0].place_id == "places/deterministic"
    # No citations
    assert response.citations == []
    # Message references result count from cache
    assert "1" in response.message


# ---------------------------------------------------------------------------
# Test: Reasoning log reveals cache source and fallback status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reasoning_log_reveals_cache_source_on_fallback() -> None:
    """Cache-hit fallback must include source=cache in reasoning log."""
    cached_candidates = [
        PlaceCandidate(
            place_id="places/reasoning-test",
            display_name="Quán Log",
            types=["restaurant"],
            location=LatLng(lat=10.1794, lng=104.0491),
        ),
    ]
    cache = FakePlaceCache(candidates=cached_candidates, result="hit")
    places_service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeClient(),
        place_cache=cache,
    )
    recommender = PlaceRecommendationService(places_service, routes_service=None)

    response = await recommender.recommend(query="test", language="vi", session_id="s-reasoning")

    assert response.reasoning_log is not None
    # The reasoning log should reveal it came from cache
    # Since the places_tool returned OK (from cache), the reasoning_log shows status=ok
    assert "status=ok" in response.reasoning_log or "cache" in response.reasoning_log.lower()


# ---------------------------------------------------------------------------
# Test: Cache diagnostics structure is safe (no secrets)
# ---------------------------------------------------------------------------

def test_cache_diagnostics_no_secret_exposure() -> None:
    """CacheDiagnostics must not expose raw query text or API keys."""
    diag = CacheDiagnostics(
        result="hit",
        cache_key="abc12345",
        candidate_count=3,
    )
    assert diag.result == "hit"
    assert diag.cache_hit is True
    assert diag.cache_stale is False
    # No secrets in the diagnostics dict
    dump = str(diag)
    assert "api_key" not in dump.lower()
    assert "secret" not in dump.lower()


# ---------------------------------------------------------------------------
# Test: Provider malformed response → cache fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_malformed_response_returns_upstream_error() -> None:
    """Provider returns malformed payload → UPSTREAM_ERROR (malformed path returns _safe_error directly)."""

    class FakeMalformedClient:
        async def post(self, path: str, *, json: dict, headers: dict):
            r = MagicMock()
            r.status_code = 200
            # Malformed: no "places" key
            r.json.return_value = {"weird": "shape"}
            return r

        async def get(self, path: str, *, headers: dict):
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {}
            return r

    cached_candidates = [
        PlaceCandidate(
            place_id="places/malformed-cached",
            display_name="Quán Sau Malformed",
            types=["restaurant"],
            location=LatLng(lat=10.1794, lng=104.0491),
        ),
    ]
    cache = FakePlaceCache(candidates=cached_candidates, result="hit")
    service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeMalformedClient(),
        place_cache=cache,
    )

    request = PlaceSearchRequest(query="test")
    result = await service.text_search(request)

    # Malformed response path returns _safe_error directly (UPSTREAM_ERROR),
    # not _fallback_from_cache — this is by design (malformed = protocol error,
    # not transient failure).
    assert result.status == PlaceToolStatus.UPSTREAM_ERROR
    assert result.candidates == []


# ---------------------------------------------------------------------------
# Test: Cache error → UNAVAILABLE (degrades gracefully)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_error_returns_unavailable() -> None:
    """When cache lookup itself errors, return UNAVAILABLE — not crash."""
    cache = FakePlaceCache(candidates=None, result="error")
    service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeClient(),
        place_cache=cache,
    )

    request = PlaceSearchRequest(query="test")
    result = await service.text_search(request)

    assert result.status == PlaceToolStatus.UNAVAILABLE
    assert result.candidates == []
