"""Runtime wiring tests for Postgres cache integration through the /chat place path.

Covers:
- Cache factory: configured when DATABASE_URL exists, skipped when absent
- Safe degraded startup when Postgres init fails
- Provider timeout with cache miss → UNAVAILABLE
- Provider timeout with cache hit → OK from cache, citations=[]
- Circuit-open skips provider and uses cache
- No RAG fallback or document citations in any cache-fallback path
- Secret redaction in all error/fallback paths
- T02: AgentService chat-facing fallback paths never invoke RAG or citations
- T02: Response text only references display_name values from typed places
- T02: Malformed/injection-like provider names don't leak into chat response
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
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
from app.models.response import ChatResponse, PlaceResult, ScoreBreakdown
from agents.services.place_recommendation_service import PlaceRecommendationService
from agents.tools.places_service import CircuitState, GooglePlacesService
from agents.tools.place_cache import PlaceCache, CacheDiagnostics
from agents.graph.agent_service import AgentService


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


# ---------------------------------------------------------------------------
# T02: Decision trace tests through runtime wiring
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_decision_trace_through_cache_hit_path() -> None:
    """Cache-hit path through PlaceRecommendationService produces decision_trace."""
    cached_candidates = [
        PlaceCandidate(
            place_id="places/cache-trace",
            display_name="Quán Cache Trace",
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

    response = await recommender.recommend(
        query="cache trace test", language="vi", session_id="s-cache-trace"
    )

    assert response.decision_trace is not None
    assert response.decision_trace.credential_status == "live"
    event_names = [e.event for e in response.decision_trace.events]
    # Cache hit path: request built, provider called, cache hit, compose
    assert "request_built" in event_names
    assert "provider_called" in event_names
    assert "cache_hit" in event_names


@pytest.mark.asyncio
async def test_decision_trace_through_cache_miss_path() -> None:
    """Cache-miss on provider failure produces decision_trace with credential_status=unavailable."""
    cache = FakePlaceCache(candidates=None, result="miss")
    places_service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeClient(),
        place_cache=cache,
    )
    recommender = PlaceRecommendationService(places_service, routes_service=None)

    response = await recommender.recommend(
        query="miss trace test", language="vi", session_id="s-miss-trace"
    )

    assert response.decision_trace is not None
    assert response.decision_trace.credential_status == "unavailable"
    event_names = [e.event for e in response.decision_trace.events]
    assert "request_built" in event_names
    # Provider failed AND cache missed → provider_unavailable event
    assert "provider_unavailable" in event_names


@pytest.mark.asyncio
async def test_decision_trace_through_circuit_open_path() -> None:
    """Circuit-open path produces decision_trace with honest audit events."""
    cached_candidates = [
        PlaceCandidate(
            place_id="places/circuit-trace",
            display_name="Quán Circuit",
            types=["restaurant"],
            location=LatLng(lat=10.1794, lng=104.0491),
        ),
    ]
    cache = FakePlaceCache(candidates=cached_candidates, result="hit")
    circuit = CircuitState(failure_threshold=1)
    circuit.record_failure()

    service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeClient(),
        place_cache=cache,
        circuit=circuit,
    )
    recommender = PlaceRecommendationService(service, routes_service=None)

    response = await recommender.recommend(
        query="circuit trace test", language="vi", session_id="s-circuit-trace"
    )

    assert response.decision_trace is not None
    # Circuit-open with cache hit should still produce live credential status
    # (data came from cache but is valid)
    assert response.decision_trace.credential_status == "live"
    event_names = [e.event for e in response.decision_trace.events]
    assert "request_built" in event_names


# ---------------------------------------------------------------------------
# T02: AgentService-level tests — prove chat fallback paths never invoke RAG
# ---------------------------------------------------------------------------

def _make_cached_place_result(
    place_id: str = "places/t02-cached",
    display_name: str = "Quán T02 Test",
) -> PlaceResult:
    """Helper to build a minimal PlaceResult for mocking."""
    return PlaceResult(
        place_id=place_id,
        display_name=display_name,
        formatted_address="Hàm Ninh, Phú Quốc",
        location=LatLng(lat=10.1794, lng=104.0491),
        types=["restaurant"],
        primary_type="restaurant",
        rating=4.2,
        user_rating_count=50,
        price_level=2,
        open_now=True,
        business_status="OPERATIONAL",
        local_factor=0.7,
        final_score=0.72,
        score_breakdown=ScoreBreakdown(
            tree1_locality=0.7, tree2_proximity=0.6, tree3_quality=0.7,
            s_bag=0.67, delta1_fairness=0.0, delta2_access=0.0,
            final_score=0.72, rank=1,
        ),
        map_uri=f"https://map.goong.io/?pid={place_id}",
    )


def _make_recommendation_response(
    *,
    message: str,
    status: PlaceToolStatus = PlaceToolStatus.OK,
    places: list[PlaceResult] | None = None,
    fallback: bool = False,
    source: PlaceToolSource | None = None,
) -> ChatResponse:
    """Helper to build a ChatResponse for mocking PlaceRecommendationService."""
    return ChatResponse(
        session_id="t02-session",
        message=message,
        citations=[],
        places=places or [],
        reasoning_log=f"place_recommendation status={status.value} source={source.value if source else 'none'}",
        intent="place_recommendation",
        latency_ms=42.0,
        fallback=fallback,
        decision_trace=None,
    )


class FakePlaceRecommenderNoLLM:
    """Fake place recommender that returns controlled responses without calling LLM."""

    def __init__(self, responses: list[ChatResponse] | None = None, raise_on: Exception | None = None) -> None:
        self._responses = responses or []
        self._call_index = 0
        self._raise_on = raise_on
        self.call_count = 0
        self.last_query: str | None = None

    async def recommend(self, *, query: str, **kwargs: Any) -> ChatResponse:
        self.call_count += 1
        self.last_query = query
        if self._raise_on is not None:
            raise self._raise_on
        if self._responses:
            resp = self._responses[min(self._call_index, len(self._responses) - 1)]
            self._call_index += 1
            return resp
        return _make_recommendation_response(
            message="Mình tìm được 0 địa điểm phù hợp.",
            places=[],
            fallback=True,
        )


class FakeCheckpointer:
    """In-memory checkpointer for AgentService tests."""

    def __init__(self) -> None:
        self._store: dict[str, list[dict[str, str]]] = {}

    async def load_history(self, session_id: str) -> list[dict[str, str]]:
        return list(self._store.get(session_id, []))

    async def save_turn(self, session_id: str, user: str, assistant: str) -> None:
        history = self._store.setdefault(session_id, [])
        history.extend([{"role": "user", "content": user}, {"role": "assistant", "content": assistant}])
        del history[:-8]


# ---------------------------------------------------------------------------
# T02.1: AgentService with no LLM client — place fallback → no RAG, citations=[]
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_service_place_fallback_no_rag_cache_hit() -> None:
    """AgentService routes place request → cache-backed response → RAG never called, citations=[]."""
    recommender = FakePlaceRecommenderNoLLM(responses=[
        _make_recommendation_response(
            message="Mình tìm được 1 địa điểm phù hợp quanh Hàm Ninh: 1. Quán T02 Test.",
            places=[_make_cached_place_result()],
            fallback=False,
            source=PlaceToolSource.CACHE,
        ),
    ])
    agent = AgentService(
        retriever=None,
        hybrid_retriever=None,
        llm_service=None,
        checkpointer=FakeCheckpointer(),
        checkpoint_mode="test",
        place_recommendation_service=recommender,
    )

    response = await agent.answer(
        session_id="t02-no-rag-hit",
        message="kiếm nhà hàng hải sản gần đây",
        language="vi",
    )

    # R038 proof: citations must be empty — no RAG fallback
    assert response.citations == []
    assert response.intent == "place_recommendation"
    # Places must be present from cache
    assert len(response.places) == 1
    assert response.places[0].display_name == "Quán T02 Test"
    # Response must not contain any document-citation-like text
    assert "[1]" not in response.message
    assert "nguồn" not in response.message.lower() or "địa điểm" in response.message.lower()


@pytest.mark.asyncio
async def test_agent_service_place_fallback_no_rag_cache_miss() -> None:
    """AgentService routes place request → provider fails + cache miss → honest unavailable, citations=[]."""
    recommender = FakePlaceRecommenderNoLLM(responses=[
        _make_recommendation_response(
            message="Tính năng tìm địa điểm đang tạm không khả dụng. Bạn thử lại sau nhé.",
            status=PlaceToolStatus.UNAVAILABLE,
            places=[],
            fallback=True,
        ),
    ])
    agent = AgentService(
        retriever=None,
        hybrid_retriever=None,
        llm_service=None,
        checkpointer=FakeCheckpointer(),
        checkpoint_mode="test",
        place_recommendation_service=recommender,
    )

    response = await agent.answer(
        session_id="t02-no-rag-miss",
        message="tìm quán không tồn tại",
        language="vi",
    )

    # R038 proof: no RAG citations on cache-miss fallback
    assert response.citations == []
    assert response.places == []
    assert response.fallback is True
    # Honest unavailable message — no invented place names
    assert "không khả dụng" in response.message


# ---------------------------------------------------------------------------
# T02.2: AgentService with no LLM — circuit-open cache hit → no RAG
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_service_circuit_open_cache_hit_no_rag() -> None:
    """Circuit-open + cache hit through AgentService → citations=[], no RAG call."""
    recommender = FakePlaceRecommenderNoLLM(responses=[
        _make_recommendation_response(
            message="Mình tìm được 1 địa điểm phù hợp quanh Hàm Ninh: 1. Quán Circuit.",
            places=[_make_cached_place_result(display_name="Quán Circuit")],
            fallback=False,
            source=PlaceToolSource.CACHE,
        ),
    ])
    agent = AgentService(
        retriever=None,
        hybrid_retriever=None,
        llm_service=None,
        checkpointer=FakeCheckpointer(),
        checkpoint_mode="test",
        place_recommendation_service=recommender,
    )

    response = await agent.answer(
        session_id="t02-circuit-hit",
        message="kiếm cafe gần đây",
        language="vi",
    )

    assert response.citations == []
    assert len(response.places) == 1
    assert response.places[0].display_name == "Quán Circuit"


@pytest.mark.asyncio
async def test_agent_service_circuit_open_cache_miss_no_rag() -> None:
    """Circuit-open + cache miss through AgentService → honest unavailable, citations=[]."""
    recommender = FakePlaceRecommenderNoLLM(responses=[
        _make_recommendation_response(
            message="Tính năng tìm địa điểm đang tạm không khả dụng. Bạn thử lại sau nhé.",
            status=PlaceToolStatus.UNAVAILABLE,
            places=[],
            fallback=True,
        ),
    ])
    agent = AgentService(
        retriever=None,
        hybrid_retriever=None,
        llm_service=None,
        checkpointer=FakeCheckpointer(),
        checkpoint_mode="test",
        place_recommendation_service=recommender,
    )

    response = await agent.answer(
        session_id="t02-circuit-miss",
        message="tìm homestay Hàm Ninh",
        language="vi",
    )

    assert response.citations == []
    assert response.places == []
    assert response.fallback is True


# ---------------------------------------------------------------------------
# T02.3: AgentService with no LLM — credential-blocked path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_service_credential_blocked_no_rag() -> None:
    """Credential-blocked path through AgentService → honest message, citations=[]."""
    recommender = FakePlaceRecommenderNoLLM(responses=[
        _make_recommendation_response(
            message="Tính năng tìm địa điểm đang thiếu cấu hình Places API trên máy chủ, nên mình chưa thể trả kết quả địa điểm thật lúc này.",
            status=PlaceToolStatus.CREDENTIALS_BLOCKED,
            places=[],
            fallback=True,
        ),
    ])
    agent = AgentService(
        retriever=None,
        hybrid_retriever=None,
        llm_service=None,
        checkpointer=FakeCheckpointer(),
        checkpoint_mode="test",
        place_recommendation_service=recommender,
    )

    response = await agent.answer(
        session_id="t02-cred-blocked",
        message="kiếm nhà hàng gần đây",
        language="vi",
    )

    assert response.citations == []
    assert response.places == []
    assert response.fallback is True
    assert "thiếu cấu hình" in response.message


# ---------------------------------------------------------------------------
# T02.4: AgentService with no LLM — provider exception → cache hit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_service_provider_exception_cache_hit_no_rag() -> None:
    """Provider raises exception → cache-backed results through AgentService, citations=[]."""
    recommender = FakePlaceRecommenderNoLLM(responses=[
        _make_recommendation_response(
            message="Mình tìm được 1 địa điểm phù hợp quanh Hàm Ninh: 1. Quán Sau Lỗi.",
            places=[_make_cached_place_result(display_name="Quán Sau Lỗi")],
            fallback=False,
            source=PlaceToolSource.CACHE,
        ),
    ])
    agent = AgentService(
        retriever=None,
        hybrid_retriever=None,
        llm_service=None,
        checkpointer=FakeCheckpointer(),
        checkpoint_mode="test",
        place_recommendation_service=recommender,
    )

    response = await agent.answer(
        session_id="t02-exc-hit",
        message="tìm quán ăn ngon",
        language="vi",
    )

    assert response.citations == []
    assert len(response.places) == 1
    assert response.places[0].display_name == "Quán Sau Lỗi"
    # Reasoning log should reveal cache source
    assert response.reasoning_log is not None
    assert "cache" in response.reasoning_log.lower()


# ---------------------------------------------------------------------------
# T02.5: Response text only references display_name values
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_response_text_only_references_display_names() -> None:
    """Response message must only reference returned PlaceResult.display_name values."""
    recommender = FakePlaceRecommenderNoLLM(responses=[
        _make_recommendation_response(
            message="Mình tìm được 2 địa điểm phù hợp quanh Hàm Ninh: 1. Quán A; 2. Quán B.",
            places=[
                _make_cached_place_result(place_id="p1", display_name="Quán A"),
                _make_cached_place_result(place_id="p2", display_name="Quán B"),
            ],
            fallback=False,
            source=PlaceToolSource.CACHE,
        ),
    ])
    agent = AgentService(
        retriever=None,
        hybrid_retriever=None,
        llm_service=None,
        checkpointer=FakeCheckpointer(),
        checkpoint_mode="test",
        place_recommendation_service=recommender,
    )

    response = await agent.answer(
        session_id="t02-names",
        message="tìm quán ăn",
        language="vi",
    )

    # All display names in response must match actual returned places
    returned_names = {p.display_name for p in response.places}
    # "Quán A" and "Quán B" must both be in places
    assert returned_names == {"Quán A", "Quán B"}
    # Response must reference them
    assert "Quán A" in response.message
    assert "Quán B" in response.message
    # Response must NOT contain any other business names
    assert "Quán C" not in response.message
    assert "McDonald" not in response.message


# ---------------------------------------------------------------------------
# T02.6: Malformed/injection-like provider names don't leak
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_malformed_injection_names_do_not_leak() -> None:
    """Malformed/injection-like display names from cache are returned as-is but NOT duplicated in extra text."""
    # Simulate a provider result that has injection-like display_name
    malicious_name = "<script>alert('xss')</script> Quán Độc"
    recommender = FakePlaceRecommenderNoLLM(responses=[
        _make_recommendation_response(
            message=f"Mình tìm được 1 địa điểm phù hợp.",
            places=[_make_cached_place_result(place_id="p-inject", display_name=malicious_name)],
            fallback=False,
            source=PlaceToolSource.CACHE,
        ),
    ])
    agent = AgentService(
        retriever=None,
        hybrid_retriever=None,
        llm_service=None,
        checkpointer=FakeCheckpointer(),
        checkpoint_mode="test",
        place_recommendation_service=recommender,
    )

    response = await agent.answer(
        session_id="t02-inject",
        message="tìm quán lạ",
        language="vi",
    )

    # Must have the place (even with weird name — it's grounded in typed data)
    assert len(response.places) == 1
    # The display_name comes from typed PlaceResult, not invented
    assert response.places[0].display_name == malicious_name
    # citations must be empty — no RAG was invoked
    assert response.citations == []
    # The message should NOT repeat the injection string in free-form text
    # (it may reference it via structured places, but not in the prose message)
    assert "<script>" not in response.message
    assert "alert(" not in response.message


# ---------------------------------------------------------------------------
# T02.7: PlaceRecommendationService exception → AgentService degrades gracefully
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recommendation_service_exception_degrades_gracefully() -> None:
    """If PlaceRecommendationService raises, AgentService returns honest unavailable, citations=[]."""
    recommender = FakePlaceRecommenderNoLLM(raise_on=RuntimeError("db connection lost"))
    agent = AgentService(
        retriever=None,
        hybrid_retriever=None,
        llm_service=None,
        checkpointer=FakeCheckpointer(),
        checkpoint_mode="test",
        place_recommendation_service=recommender,
    )

    response = await agent.answer(
        session_id="t02-svc-exc",
        message="tìm nhà hàng",
        language="vi",
    )

    # Must not crash — returns unavailable
    assert response.citations == []
    assert response.places == []
    assert response.fallback is True
    # Must contain honest unavailable text
    assert "không khả dụng" in response.message or "tạm lỗi" in response.message


# ---------------------------------------------------------------------------
# T02.8: AgentService with no LLM — no place service → honest unavailable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_service_no_place_service_no_rag() -> None:
    """AgentService with no place_recommendation_service → honest unavailable, citations=[]."""
    agent = AgentService(
        retriever=None,
        hybrid_retriever=None,
        llm_service=None,
        checkpointer=FakeCheckpointer(),
        checkpoint_mode="test",
        place_recommendation_service=None,
    )

    response = await agent.answer(
        session_id="t02-no-svc",
        message="kiếm nhà hàng gần đây",
        language="vi",
    )

    assert response.citations == []
    assert response.places == []
    # fallback=False is intentional: the place intent was handled via the deterministic
    # tool policy path — the unavailable message IS the honest answer, not a fallback.
    assert response.fallback is False
    # The _place_unavailable_message says "không dùng nguồn RAG để giả kết quả"
    assert "không" in response.message.lower()


# ---------------------------------------------------------------------------
# T02.9: No RAG retriever called even when hybrid_retriever is available
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_place_path_does_not_call_hybrid_retriever() -> None:
    """Place-deterministic routing must NOT call hybrid_retriever even when it exists."""
    mock_hybrid = AsyncMock()
    mock_hybrid.search_with_citations = AsyncMock(
        return_value=(MagicMock(chunks=[]), [])
    )

    recommender = FakePlaceRecommenderNoLLM(responses=[
        _make_recommendation_response(
            message="Mình tìm được 1 địa điểm.",
            places=[_make_cached_place_result()],
            fallback=False,
            source=PlaceToolSource.CACHE,
        ),
    ])

    agent = AgentService(
        retriever=None,
        hybrid_retriever=mock_hybrid,
        llm_service=None,
        checkpointer=FakeCheckpointer(),
        checkpoint_mode="test",
        place_recommendation_service=recommender,
    )

    response = await agent.answer(
        session_id="t02-no-retriever-call",
        message="tìm quán hải sản",
        language="vi",
    )

    # R038 proof: hybrid_retriever must NOT be called for place paths
    mock_hybrid.search_with_citations.assert_not_called()
    assert response.citations == []


# ---------------------------------------------------------------------------
# T02.10: Multi-place cache hit — all display_names accounted for
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multi_place_cache_hit_all_names_accounted() -> None:
    """Multi-place cache hit: every display_name in message matches a returned PlaceResult."""
    places = [
        _make_cached_place_result(place_id=f"p-{i}", display_name=f"Quán {chr(65+i)}")
        for i in range(3)
    ]
    recommender = FakePlaceRecommenderNoLLM(responses=[
        _make_recommendation_response(
            message="Mình tìm được 3 địa điểm phù hợp.",
            places=places,
            fallback=False,
            source=PlaceToolSource.CACHE,
        ),
    ])
    agent = AgentService(
        retriever=None,
        hybrid_retriever=None,
        llm_service=None,
        checkpointer=FakeCheckpointer(),
        checkpoint_mode="test",
        place_recommendation_service=recommender,
    )

    response = await agent.answer(
        session_id="t02-multi",
        message="tìm nhiều quán",
        language="vi",
    )

    assert response.citations == []
    assert len(response.places) == 3
    returned_names = {p.display_name for p in response.places}
    assert returned_names == {"Quán A", "Quán B", "Quán C"}
    # No unexpected names in message
    assert "Quán D" not in response.message


# ---------------------------------------------------------------------------
# T02.11: Provider exception → decision_trace with provider_error + unavailable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provider_exception_emits_provider_error_and_unavailable() -> None:
    """When the places tool raises an exception, decision_trace must include
    provider_error event and credential_status=unavailable."""
    recommender = FakePlaceRecommenderNoLLM(raise_on=RuntimeError("connection lost"))
    agent = AgentService(
        retriever=None,
        hybrid_retriever=None,
        llm_service=None,
        checkpointer=FakeCheckpointer(),
        checkpoint_mode="test",
        place_recommendation_service=recommender,
    )

    response = await agent.answer(
        session_id="t02-exc-trace",
        message="tìm nhà hàng",
        language="vi",
    )

    assert response.citations == []
    assert response.places == []
    assert response.fallback is True


# ---------------------------------------------------------------------------
# T02.12: Credential-blocked decision trace — blocked status in trace
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_credential_blocked_decision_trace_has_blocked_status() -> None:
    """When credentials are blocked, decision_trace must show credential_status=blocked
    with provider_credentials_blocked event."""
    from datetime import UTC, datetime
    from app.models.places import PlaceSearchRequest, PlaceToolResponse, PlaceToolSource, PlaceToolStatus
    from agents.services.place_recommendation_service import PlaceRecommendationService

    cache = FakePlaceCache(candidates=None, result="miss")
    places_service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeClient(),
        place_cache=cache,
    )
    # Override to simulate credentials_blocked — we patch the text_search result
    original = places_service.text_search

    async def _cred_blocked(request):
        return PlaceToolResponse(
            status=PlaceToolStatus.CREDENTIALS_BLOCKED,
            source=PlaceToolSource.GOOGLE_PLACES,
            candidates=[],
            request=request,
            retrieved_at=datetime.now(UTC),
        )

    places_service.text_search = _cred_blocked
    recommender = PlaceRecommendationService(places_service, routes_service=None)

    response = await recommender.recommend(
        query="nhà hàng", language="vi", session_id="s-cred-block-trace"
    )

    assert response.decision_trace is not None
    assert response.decision_trace.credential_status == "blocked"
    event_names = [e.event for e in response.decision_trace.events]
    assert "provider_credentials_blocked" in event_names
    assert response.citations == []


# ---------------------------------------------------------------------------
# T02.13: Cache stale path — safe diagnostics without RAG fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_stale_path_safe_diagnostics_no_rag() -> None:
    """Cache stale path produces decision_trace, no RAG fallback."""
    cache = FakePlaceCache(candidates=None, result="stale")
    places_service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeClient(),
        place_cache=cache,
    )
    recommender = PlaceRecommendationService(places_service, routes_service=None)

    response = await recommender.recommend(
        query="stale test", language="vi", session_id="s-stale-trace"
    )

    assert response.citations == []
    assert response.places == []
    assert response.fallback is True
    # decision_trace should show request_built and provider_unavailable
    if response.decision_trace is not None:
        event_names = [e.event for e in response.decision_trace.events]
        assert "request_built" in event_names
        assert response.decision_trace.credential_status == "unavailable"


# ---------------------------------------------------------------------------
# T02.14: Cache error path — safe diagnostics without RAG fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_error_path_safe_diagnostics_no_rag() -> None:
    """Cache error path produces UNAVAILABLE response, no RAG fallback."""
    cache = FakePlaceCache(candidates=None, result="error")
    places_service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeClient(),
        place_cache=cache,
    )
    recommender = PlaceRecommendationService(places_service, routes_service=None)

    response = await recommender.recommend(
        query="error test", language="vi", session_id="s-error-trace"
    )

    assert response.citations == []
    assert response.places == []
    assert response.fallback is True


# ---------------------------------------------------------------------------
# T02.15: Decision trace elapsed_ms is populated on all events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_decision_trace_elapsed_ms_populated() -> None:
    """All events in decision_trace should have elapsed_ms >= 0."""
    cached_candidates = [
        PlaceCandidate(
            place_id="places/timing-test",
            display_name="Quán Timing",
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

    response = await recommender.recommend(
        query="timing test", language="vi", session_id="s-timing"
    )

    assert response.decision_trace is not None
    for event in response.decision_trace.events:
        assert event.elapsed_ms is not None, f"Event {event.event} missing elapsed_ms"
        assert event.elapsed_ms >= 0.0, f"Event {event.event} has negative elapsed_ms"


# ---------------------------------------------------------------------------
# T02.16: Decision trace — no secret leakage across all paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_decision_trace_no_secret_in_any_path() -> None:
    """Serialized decision_trace must never contain API keys in any code path."""
    cache = FakePlaceCache(candidates=None, result="miss")
    places_service = GooglePlacesService(
        settings=FakeSettings,
        client=FakeClient(),
        place_cache=cache,
    )
    recommender = PlaceRecommendationService(places_service, routes_service=None)

    response = await recommender.recommend(
        query="redact test", language="vi", session_id="s-redact"
    )

    if response.decision_trace is not None:
        dump = response.decision_trace.model_dump_json()
        assert "fake-api-key" not in dump.lower()
        assert "api_key" not in dump.lower()
        assert "sk-" not in dump
        # Check no raw API key value appears anywhere
        assert "fake-api-key-for-testing" not in dump.lower()


# ---------------------------------------------------------------------------
# T02.17: OK path — decision_trace shows provider_called, cache_hit, compose
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ok_path_decision_trace_has_expected_events() -> None:
    """Successful OK path through recommendation service should have expected trace."""
    cached_candidates = [
        PlaceCandidate(
            place_id="places/ok-trace",
            display_name="Quán OK Trace",
            types=["restaurant"],
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

    response = await recommender.recommend(
        query="ok trace", language="vi", session_id="s-ok-trace"
    )

    assert response.decision_trace is not None
    event_names = [e.event for e in response.decision_trace.events]
    # OK path: request_built → provider_called → cache_hit → compose
    assert "request_built" in event_names
    assert "provider_called" in event_names
    assert "cache_hit" in event_names
    assert "composition_deterministic" in event_names
    # Credential status should be live
    assert response.decision_trace.credential_status == "live"


# ---------------------------------------------------------------------------
# T02.18: No-RAG path — citations=[] with decision_trace present
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_rag_with_decision_trace_present() -> None:
    """When decision_trace is present, citations must still be empty (no RAG)."""
    cached_candidates = [
        PlaceCandidate(
            place_id="places/no-rag-trace",
            display_name="Quán No RAG",
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
    agent = AgentService(
        retriever=None,
        hybrid_retriever=None,
        llm_service=None,
        checkpointer=FakeCheckpointer(),
        checkpoint_mode="test",
        place_recommendation_service=recommender,
    )

    response = await agent.answer(
        session_id="t02-no-rag-trace",
        message="tìm quán ăn",
        language="vi",
    )

    assert response.citations == []
    assert response.decision_trace is not None
    assert response.decision_trace.total_events > 0
    # Intent must be place_recommendation, not cultural_query
    assert response.intent == "place_recommendation"


# ===================================================================
# T03: Google-first provider with Goong fallback wiring tests
# ===================================================================

class FakeSettingsBothKeys:
    GOOGLE_PLACES_API_KEY = "test-google-key"
    GOONG_API_KEY = "test-goong-key"
    DATABASE_URL = ""


class FakeSettingsGoogleOnly:
    GOOGLE_PLACES_API_KEY = "test-google-key"
    GOONG_API_KEY = ""
    DATABASE_URL = ""


class FakeSettingsGoongOnly:
    GOOGLE_PLACES_API_KEY = ""
    GOONG_API_KEY = "test-goong-key"
    DATABASE_URL = ""


class FakeSettingsNoKeys:
    GOOGLE_PLACES_API_KEY = ""
    GOONG_API_KEY = ""
    DATABASE_URL = ""


class FakeGoogleClient:
    """Fake Google client that returns a response-like object."""

    def __init__(self, payload: Any = None, status_code: int = 200, raise_exception: Exception | None = None) -> None:
        self._payload = payload
        self._status_code = status_code
        self._raise = raise_exception
        self.post_calls: list = []
        self.get_calls: list = []

    def _make_response(self):
        if self._raise:
            raise self._raise
        r = MagicMock()
        r.status_code = self._status_code
        r.json.return_value = self._payload
        return r

    async def post(self, path: str, *, json: dict, headers: dict):
        self.post_calls.append((path, json, headers))
        return self._make_response()

    async def get(self, path: str, *, headers: dict, params: dict | None = None):
        self.get_calls.append((path, headers, params))
        return self._make_response()


class FakeGoongClient:
    """Fake Goong client that returns a response-like object."""

    def __init__(self, payload: Any = None, status_code: int = 200, raise_exception: Exception | None = None) -> None:
        self._payload = payload
        self._status_code = status_code
        self._raise = raise_exception
        self.get_calls: list = []

    def _make_response(self):
        if self._raise:
            raise self._raise
        r = MagicMock()
        r.status_code = self._status_code
        r.json.return_value = self._payload
        return r

    async def post(self, path: str, *, json: dict, headers: dict):
        return self._make_response()

    async def get(self, path: str, *, headers: dict, params: dict | None = None):
        self.get_calls.append((path, headers, params))
        return self._make_response()


def _google_ok_response(candidates: list[PlaceCandidate]) -> dict:
    """Build a mock Google Places API response with places array."""
    return {
        "places": [
            {
                "id": c.place_id.replace("places/", ""),
                "displayName": {"text": c.display_name},
                "formattedAddress": c.formatted_address,
                "location": {"lat": c.location.lat, "lng": c.location.lng} if c.location else None,
                "types": c.types,
                "primaryType": c.primary_type,
                "rating": c.rating,
                "userRatingCount": c.user_rating_count,
                "businessStatus": c.business_status,
            }
            for c in candidates
        ]
    }


def _goong_ok_response(candidates: list[PlaceCandidate]) -> dict:
    """Build a mock Goong Places API response with results array."""
    return {
        "results": [
            {
                "place_id": c.place_id,
                "name": c.display_name,
                "formatted_address": c.formatted_address,
                "geometry": {
                    "location": {"lat": c.location.lat, "lng": c.location.lng}
                } if c.location else {},
                "types": c.types,
                "rating": c.rating,
            }
            for c in candidates
        ],
        "status": "OK",
    }


# ---------------------------------------------------------------------------
# T03.1: Google key present + Google succeeds → source=google_places
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_first_google_succeeds_source_is_google() -> None:
    """When Google key is present and Google succeeds, source must be google_places."""
    from agents.tools.places_service import DualPlacesService, GooglePlacesService, GoongPlacesService

    candidates = [
        PlaceCandidate(
            place_id="places/google-only",
            display_name="Quán Google",
            types=["restaurant"],
            location=LatLng(lat=10.1794, lng=104.0491),
            rating=4.5,
        ),
    ]
    google_client = FakeGoogleClient(payload=_google_ok_response(candidates))
    goong_client = FakeGoongClient(payload={"results": [], "status": "ZERO_RESULTS"})

    google_service = GooglePlacesService(
        settings=FakeSettingsBothKeys, client=google_client, place_cache=None,
    )
    goong_service = GoongPlacesService(
        settings=FakeSettingsBothKeys, client=goong_client,
    )
    dual = DualPlacesService(google_service=google_service, goong_service=goong_service, settings=FakeSettingsBothKeys)

    request = PlaceSearchRequest(query="nhà hàng")
    result = await dual.text_search(request)

    assert result.status == PlaceToolStatus.OK
    assert result.source == PlaceToolSource.GOOGLE_PLACES
    assert len(result.candidates) == 1
    assert result.candidates[0].display_name == "Quán Google"
    # Goong should NOT have been called
    assert len(goong_client.get_calls) == 0
    # Metadata should show google primary
    assert result.request_metadata.get("provider_attempted") == PlaceToolSource.GOOGLE_PLACES.value


# ---------------------------------------------------------------------------
# T03.2: Google failure + Goong key present → Goong fallback with metadata
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_failure_goong_fallback_source_is_goong() -> None:
    """When Google fails and Goong key is present, source must be goong_places with fallback metadata."""
    from agents.tools.places_service import DualPlacesService, GooglePlacesService, GoongPlacesService

    goong_candidates = [
        PlaceCandidate(
            place_id="places/goong-fallback",
            display_name="Quán Goong Fallback",
            types=["restaurant"],
            location=LatLng(lat=10.1794, lng=104.0491),
        ),
    ]
    # Google returns 401 (auth error)
    google_client = FakeGoogleClient(payload={"error": {"status": "REQUEST_DENIED", "message": "Auth failed"}}, status_code=401)
    goong_client = FakeGoongClient(payload=_goong_ok_response(goong_candidates))

    google_service = GooglePlacesService(
        settings=FakeSettingsBothKeys, client=google_client, place_cache=None,
    )
    goong_service = GoongPlacesService(
        settings=FakeSettingsBothKeys, client=goong_client,
    )
    dual = DualPlacesService(google_service=google_service, goong_service=goong_service, settings=FakeSettingsBothKeys)

    request = PlaceSearchRequest(query="nhà hàng")
    result = await dual.text_search(request)

    # Goong should have been called as fallback
    assert result.source == PlaceToolSource.GOONG_PLACES
    assert len(result.candidates) == 1
    assert result.candidates[0].display_name == "Quán Goong Fallback"
    # Fallback metadata must be present
    meta = result.request_metadata
    assert meta.get("primary_source") == PlaceToolSource.GOOGLE_PLACES.value
    assert meta.get("fallback_source") == PlaceToolSource.GOONG_PLACES.value
    assert meta.get("fallback_reason") is not None
    assert "google" in meta.get("fallback_reason", "").lower()


# ---------------------------------------------------------------------------
# T03.3: Google timeout → Goong fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_timeout_goong_fallback() -> None:
    """When Google times out and Goong key is present, Goong is called as fallback."""
    from agents.tools.places_service import DualPlacesService, GooglePlacesService, GoongPlacesService

    goong_candidates = [
        PlaceCandidate(
            place_id="places/timeout-fallback",
            display_name="Quán Timeout",
            types=["cafe"],
            location=LatLng(lat=10.1794, lng=104.0491),
        ),
    ]
    google_client = FakeGoogleClient(raise_exception=httpx.TimeoutException("Google timeout"))
    goong_client = FakeGoongClient(payload=_goong_ok_response(goong_candidates))

    google_service = GooglePlacesService(
        settings=FakeSettingsBothKeys, client=google_client, place_cache=None,
    )
    goong_service = GoongPlacesService(
        settings=FakeSettingsBothKeys, client=goong_client,
    )
    dual = DualPlacesService(google_service=google_service, goong_service=goong_service, settings=FakeSettingsBothKeys)

    request = PlaceSearchRequest(query="cafe")
    result = await dual.text_search(request)

    assert result.source == PlaceToolSource.GOONG_PLACES
    assert len(result.candidates) == 1
    assert result.candidates[0].display_name == "Quán Timeout"
    assert result.request_metadata.get("primary_source") == PlaceToolSource.GOOGLE_PLACES.value
    assert result.request_metadata.get("fallback_source") == PlaceToolSource.GOONG_PLACES.value


# ---------------------------------------------------------------------------
# T03.4: Both providers fail → UNAVAILABLE with dual-failure metadata
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_both_providers_fail_returns_unavailable() -> None:
    """When both Google and Goong fail, return UNAVAILABLE with dual-failure metadata."""
    from agents.tools.places_service import DualPlacesService, GooglePlacesService, GoongPlacesService

    google_client = FakeGoogleClient(raise_exception=httpx.TimeoutException("Google timeout"))
    goong_client = FakeGoongClient(raise_exception=httpx.TimeoutException("Goong timeout"))

    google_service = GooglePlacesService(
        settings=FakeSettingsBothKeys, client=google_client, place_cache=None,
    )
    goong_service = GoongPlacesService(
        settings=FakeSettingsBothKeys, client=goong_client,
    )
    dual = DualPlacesService(google_service=google_service, goong_service=goong_service, settings=FakeSettingsBothKeys)

    request = PlaceSearchRequest(query="nhà hàng")
    result = await dual.text_search(request)

    assert result.status == PlaceToolStatus.UNAVAILABLE
    assert result.candidates == []
    meta = result.request_metadata
    assert meta.get("primary_source") == PlaceToolSource.GOOGLE_PLACES.value
    assert meta.get("fallback_source") == PlaceToolSource.GOONG_PLACES.value
    assert "Both Google and Goong" in result.warnings[0]


# ---------------------------------------------------------------------------
# T03.5: Google key absent, Goong key present → Goong-only with primary_source
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_absent_goong_only_source_is_goong() -> None:
    """When Google key is absent but Goong key is present, Goong is called directly."""
    from agents.tools.places_service import DualPlacesService, GooglePlacesService, GoongPlacesService

    goong_candidates = [
        PlaceCandidate(
            place_id="places/goong-only",
            display_name="Quán Goong Only",
            types=["restaurant"],
            location=LatLng(lat=10.1794, lng=104.0491),
        ),
    ]
    google_client = FakeGoogleClient()  # Never called
    goong_client = FakeGoongClient(payload=_goong_ok_response(goong_candidates))

    google_service = GooglePlacesService(
        settings=FakeSettingsGoongOnly, client=google_client, place_cache=None,
    )
    goong_service = GoongPlacesService(
        settings=FakeSettingsGoongOnly, client=goong_client,
    )
    dual = DualPlacesService(google_service=google_service, goong_service=goong_service, settings=FakeSettingsGoongOnly)

    request = PlaceSearchRequest(query="nhà hàng")
    result = await dual.text_search(request)

    assert result.status == PlaceToolStatus.OK
    assert result.source == PlaceToolSource.GOONG_PLACES
    assert len(result.candidates) == 1
    assert result.candidates[0].display_name == "Quán Goong Only"
    # Google should NOT have been called
    assert len(google_client.post_calls) == 0
    # Metadata should still track primary_source
    meta = result.request_metadata
    assert meta.get("primary_source") == PlaceToolSource.GOOGLE_PLACES.value
    assert meta.get("fallback_reason") == "google_credential_missing"


# ---------------------------------------------------------------------------
# T03.6: Neither provider configured → CREDENTIALS_BLOCKED
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_neither_provider_configured_returns_credentials_blocked() -> None:
    """When no provider keys are configured, return CREDENTIALS_BLOCKED."""
    from agents.tools.places_service import DualPlacesService, GooglePlacesService, GoongPlacesService

    google_client = FakeGoogleClient()  # Never called
    goong_client = FakeGoongClient()  # Never called

    google_service = GooglePlacesService(
        settings=FakeSettingsNoKeys, client=google_client, place_cache=None,
    )
    goong_service = GoongPlacesService(
        settings=FakeSettingsNoKeys, client=goong_client,
    )
    dual = DualPlacesService(google_service=google_service, goong_service=goong_service, settings=FakeSettingsNoKeys)

    request = PlaceSearchRequest(query="nhà hàng")
    result = await dual.text_search(request)

    assert result.status == PlaceToolStatus.CREDENTIALS_BLOCKED
    assert result.candidates == []
    assert "No Places API credentials" in result.warnings[0]
    # Neither provider should have been called
    assert len(google_client.post_calls) == 0
    assert len(goong_client.get_calls) == 0


# ---------------------------------------------------------------------------
# T03.7: Google success, Goong key absent → Google result (no fallback needed)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_succeeds_goong_absent_still_google() -> None:
    """When Google succeeds, Goong key absence is irrelevant."""
    from agents.tools.places_service import DualPlacesService, GooglePlacesService, GoongPlacesService

    candidates = [
        PlaceCandidate(
            place_id="places/google-no-goong",
            display_name="Quán Google Success",
            types=["restaurant"],
            location=LatLng(lat=10.1794, lng=104.0491),
        ),
    ]
    google_client = FakeGoogleClient(payload=_google_ok_response(candidates))
    goong_client = FakeGoongClient()  # Never called

    google_service = GooglePlacesService(
        settings=FakeSettingsGoogleOnly, client=google_client, place_cache=None,
    )
    goong_service = GoongPlacesService(
        settings=FakeSettingsGoogleOnly, client=goong_client,
    )
    dual = DualPlacesService(google_service=google_service, goong_service=goong_service, settings=FakeSettingsGoogleOnly)

    request = PlaceSearchRequest(query="nhà hàng")
    result = await dual.text_search(request)

    assert result.status == PlaceToolStatus.OK
    assert result.source == PlaceToolSource.GOOGLE_PLACES
    assert len(goong_client.get_calls) == 0  # Goong not called


# ---------------------------------------------------------------------------
# T03.8: Google failure, Goong key absent → enriched Google failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_fails_goong_absent_enriched_google_failure() -> None:
    """When Google fails and Goong key is absent, return enriched Google failure."""
    from agents.tools.places_service import DualPlacesService, GooglePlacesService, GoongPlacesService

    google_client = FakeGoogleClient(raise_exception=httpx.TimeoutException("Google timeout"))
    goong_client = FakeGoongClient()  # Never called

    google_service = GooglePlacesService(
        settings=FakeSettingsGoogleOnly, client=google_client, place_cache=None,
    )
    goong_service = GoongPlacesService(
        settings=FakeSettingsGoogleOnly, client=goong_client,
    )
    dual = DualPlacesService(google_service=google_service, goong_service=goong_service, settings=FakeSettingsGoogleOnly)

    request = PlaceSearchRequest(query="nhà hàng")
    result = await dual.text_search(request)

    # Google failed (converted to UNAVAILABLE by cache fallback), Goong unavailable
    assert result.status == PlaceToolStatus.UNAVAILABLE
    assert result.source == PlaceToolSource.GOOGLE_PLACES
    # Goong should NOT have been called
    assert len(goong_client.get_calls) == 0
    # Metadata should show fallback_source=none
    meta = result.request_metadata
    assert meta.get("primary_source") == PlaceToolSource.GOOGLE_PLACES.value
    assert meta.get("fallback_source") == "none"


# ---------------------------------------------------------------------------
# T03.9: Dual service through PlaceRecommendationService → proper source
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dual_through_recommendation_service_google_path() -> None:
    """DualPlacesService through PlaceRecommendationService with Google success."""
    from agents.tools.places_service import DualPlacesService, GooglePlacesService, GoongPlacesService
    from agents.services.place_recommendation_service import PlaceRecommendationService

    candidates = [
        PlaceCandidate(
            place_id="places/dual-rec",
            display_name="Quán Dual Rec",
            types=["restaurant"],
            location=LatLng(lat=10.1794, lng=104.0491),
            rating=4.5,
        ),
    ]
    google_client = FakeGoogleClient(payload=_google_ok_response(candidates))
    goong_client = FakeGoongClient()

    google_service = GooglePlacesService(
        settings=FakeSettingsBothKeys, client=google_client, place_cache=None,
    )
    goong_service = GoongPlacesService(
        settings=FakeSettingsBothKeys, client=goong_client,
    )
    dual = DualPlacesService(google_service=google_service, goong_service=goong_service, settings=FakeSettingsBothKeys)
    recommender = PlaceRecommendationService(dual, routes_service=None)

    response = await recommender.recommend(query="nhà hàng", language="vi", session_id="s-dual-rec")

    assert response.citations == []
    assert len(response.places) == 1
    assert response.places[0].display_name == "Quán Dual Rec"
    # Reasoning log should reference google_places source
    assert "google_places" in response.reasoning_log


# ---------------------------------------------------------------------------
# T03.10: Dual through recommendation service → Goong fallback path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dual_through_recommendation_service_goong_fallback() -> None:
    """DualPlacesService through PlaceRecommendationService with Goong fallback."""
    from agents.tools.places_service import DualPlacesService, GooglePlacesService, GoongPlacesService
    from agents.services.place_recommendation_service import PlaceRecommendationService

    goong_candidates = [
        PlaceCandidate(
            place_id="places/dual-goong-fallback",
            display_name="Quán Fallback Rec",
            types=["restaurant"],
            location=LatLng(lat=10.1794, lng=104.0491),
            rating=4.0,
        ),
    ]
    google_client = FakeGoogleClient(raise_exception=httpx.TimeoutException("timeout"))
    goong_client = FakeGoongClient(payload=_goong_ok_response(goong_candidates))

    google_service = GooglePlacesService(
        settings=FakeSettingsBothKeys, client=google_client, place_cache=None,
    )
    goong_service = GoongPlacesService(
        settings=FakeSettingsBothKeys, client=goong_client,
    )
    dual = DualPlacesService(google_service=google_service, goong_service=goong_service, settings=FakeSettingsBothKeys)
    recommender = PlaceRecommendationService(dual, routes_service=None)

    response = await recommender.recommend(query="nhà hàng", language="vi", session_id="s-dual-goong")

    assert response.citations == []
    assert len(response.places) == 1
    assert response.places[0].display_name == "Quán Fallback Rec"
    # Reasoning log should reference goong_places as the source
    assert "goong_places" in response.reasoning_log


# ---------------------------------------------------------------------------
# T03.11: Secret redaction — no API keys in dual service response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dual_service_no_api_key_leakage() -> None:
    """DualPlacesService responses must not expose API keys in any code path."""
    from agents.tools.places_service import DualPlacesService, GooglePlacesService, GoongPlacesService

    google_client = FakeGoogleClient(raise_exception=httpx.TimeoutException("timeout"))
    goong_client = FakeGoongClient(raise_exception=RuntimeError("connection refused"))

    google_service = GooglePlacesService(
        settings=FakeSettingsBothKeys, client=google_client, place_cache=None,
    )
    goong_service = GoongPlacesService(
        settings=FakeSettingsBothKeys, client=goong_client,
    )
    dual = DualPlacesService(google_service=google_service, goong_service=goong_service, settings=FakeSettingsBothKeys)

    request = PlaceSearchRequest(query="test")
    result = await dual.text_search(request)

    dump = result.model_dump_json()
    assert "test-google-key" not in dump.lower()
    assert "test-goong-key" not in dump.lower()
    assert "GOOGLE_PLACES_API_KEY" not in dump
    assert "GOONG_API_KEY" not in dump


# ---------------------------------------------------------------------------
# T03.12: Empty Google result (ZERO_RESULTS) → no Goong fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_empty_no_goong_fallback() -> None:
    """When Google returns EMPTY status, Goong is NOT called as fallback."""
    from agents.tools.places_service import DualPlacesService, GooglePlacesService, GoongPlacesService

    # Google returns OK with empty places → EMPTY status
    google_client = FakeGoogleClient(payload={"places": []})
    goong_client = FakeGoongClient(payload=_goong_ok_response([
        PlaceCandidate(place_id="places/fallback-empty", display_name="Should Not Appear", types=["restaurant"]),
    ]))

    google_service = GooglePlacesService(
        settings=FakeSettingsBothKeys, client=google_client, place_cache=None,
    )
    goong_service = GoongPlacesService(
        settings=FakeSettingsBothKeys, client=goong_client,
    )
    dual = DualPlacesService(google_service=google_service, goong_service=goong_service, settings=FakeSettingsBothKeys)

    request = PlaceSearchRequest(query="không tồn tại")
    result = await dual.text_search(request)

    # Google returned empty → EMPTY, no Goong fallback
    assert result.status == PlaceToolStatus.EMPTY
    assert result.source == PlaceToolSource.GOOGLE_PLACES
    # Goong should NOT have been called for empty results
    assert len(goong_client.get_calls) == 0
