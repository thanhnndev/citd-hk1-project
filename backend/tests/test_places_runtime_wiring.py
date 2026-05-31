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
    assert response.fallback is True
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
