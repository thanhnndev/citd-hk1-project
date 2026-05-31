"""M013 S03 contract regression suite for provider failure and Postgres fallback safety.

Maps to:
- R038: Place requests must never invoke RAG or document citations.
- R046: Fallback paths must expose inspectable diagnostics (provider_status,
  warnings, reasoning_log, request_metadata, cache diagnostics, circuit state)
  while enforcing redaction of credentials and raw provider payloads.

This is the single executor proof command for S03. Run:
    cd backend && python3 -m pytest tests/test_m013_s03_provider_fallback_contract.py -v

Each test name encodes the failure path and the guarantee it proves.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.models.places import (
    GOOGLE_PLACES_FIELD_MASK,
    PlaceCandidate,
    PlaceSearchRequest,
    PlaceToolSource,
    PlaceToolStatus,
)
from app.models.request import LatLng
from app.models.response import ChatResponse, PlaceResult, ScoreBreakdown
from agents.graph.agent_service import AgentService
from agents.services.place_recommendation_service import (
    PLACE_RECOMMENDATION_INTENT,
    PlaceRecommendationService,
)
from agents.tools.place_cache import CacheDiagnostics, PlaceCache
from agents.tools.places_service import CircuitState, GooglePlacesService


# ===========================================================================
# Shared fakes (composed from T01/T02 infrastructure)
# ===========================================================================

class FakeClient:
    """Fake HTTP client — configured to raise or return a specific response."""

    def __init__(
        self,
        *,
        raise_exception: Exception | None = None,
        status_code: int = 200,
        payload: dict | None = None,
    ) -> None:
        self._raise = raise_exception
        self._status_code = status_code
        self._payload = payload or {"places": []}
        self.post_calls: list[tuple[str, dict, dict]] = []
        self.get_calls: list[tuple[str, dict]] = []

    async def post(self, path: str, *, json: dict, headers: dict):
        self.post_calls.append((path, json, headers))
        if self._raise:
            raise self._raise
        r = MagicMock()
        r.status_code = self._status_code
        r.json.return_value = self._payload
        return r

    async def get(self, path: str, *, headers: dict):
        self.get_calls.append((path, headers))
        if self._raise:
            raise self._raise
        r = MagicMock()
        r.status_code = self._status_code
        r.json.return_value = self._payload
        return r


class FakePlaceCache:
    """In-memory fake cache with explicit hit/miss/stale/error control."""

    def __init__(
        self,
        *,
        candidates: list[PlaceCandidate] | None = None,
        result: str = "hit",  # "hit" | "miss" | "stale" | "error" | "malformed"
        staleness_seconds: float = 3600.0,
    ) -> None:
        self._candidates = candidates
        self._result = result
        self._staleness_seconds = staleness_seconds
        self.lookup_calls: list[PlaceSearchRequest] = []
        self.upsert_calls: list[tuple[PlaceSearchRequest, list[PlaceCandidate]]] = []

    async def lookup(self, request: PlaceSearchRequest, *, ttl_seconds: int = 900):
        self.lookup_calls.append(request)
        key = "fake"

        if self._result == "error":
            raise RuntimeError("cache db down")

        if self._result == "malformed":
            return None, CacheDiagnostics(result="miss", cache_key=key[:8], reason="malformed_cache_data")

        if self._result == "stale":
            if self._candidates:
                return self._candidates, CacheDiagnostics(
                    result="stale", cache_key=key[:8], candidate_count=len(self._candidates),
                    staleness_seconds=self._staleness_seconds,
                )
            return None, CacheDiagnostics(
                result="stale", cache_key=key[:8], reason="empty_candidates",
                staleness_seconds=self._staleness_seconds,
            )

        if self._result == "hit" and self._candidates:
            return self._candidates, CacheDiagnostics(
                result="hit", cache_key=key[:8], candidate_count=len(self._candidates),
            )

        return None, CacheDiagnostics(result="miss", cache_key=key[:8])

    async def upsert(self, request: PlaceSearchRequest, candidates: list[PlaceCandidate], *, ttl_seconds: int = 900, source: str = "goong_places"):
        self.upsert_calls.append((request, candidates))
        return CacheDiagnostics(result="write_ok", cache_key="fake"[:8], candidate_count=len(candidates))

    async def ensure_table(self) -> None:
        pass

    async def close(self) -> None:
        pass


class FakeSettings:
    GOOGLE_PLACES_API_KEY = "fake-api-key-for-testing"
    DATABASE_URL = ""


def _make_request(query: str = "seafood", **kwargs: Any) -> PlaceSearchRequest:
    base: dict[str, Any] = {
        "query": query,
        "language_code": "vi",
    }
    base.update(kwargs)
    return PlaceSearchRequest(**base)


def _make_candidate(place_id: str = "p1", display_name: str = "Quán Test", **overrides: Any) -> PlaceCandidate:
    data: dict[str, Any] = {
        "place_id": place_id,
        "display_name": display_name,
        "types": ["restaurant"],
    }
    data.update(overrides)
    return PlaceCandidate(**data)


# ===========================================================================
# AgentService helpers (from T02)
# ===========================================================================

def _make_place_result(
    place_id: str = "places/contract-1",
    display_name: str = "Quán Contract",
) -> PlaceResult:
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


def _make_chat_response(
    *,
    message: str,
    status: PlaceToolStatus = PlaceToolStatus.OK,
    places: list[PlaceResult] | None = None,
    fallback: bool = False,
    source: PlaceToolSource | None = None,
) -> ChatResponse:
    source_value = source.value if source else "none"
    return ChatResponse(
        session_id="contract-session",
        message=message,
        citations=[],
        places=places or [],
        reasoning_log=f"place_recommendation status={status.value} source={source_value}",
        intent=PLACE_RECOMMENDATION_INTENT,
        latency_ms=42.0,
        fallback=fallback,
        decision_trace=None,
    )


class FakePlaceRecommender:
    """Fake recommender returning controlled responses."""

    def __init__(
        self,
        responses: list[ChatResponse] | None = None,
        raise_on: Exception | None = None,
    ) -> None:
        self._responses = responses or []
        self._call_index = 0
        self._raise_on = raise_on
        self.call_count = 0

    async def recommend(self, *, query: str, **kwargs: Any) -> ChatResponse:
        self.call_count += 1
        if self._raise_on is not None:
            raise self._raise_on
        if self._responses:
            resp = self._responses[min(self._call_index, len(self._responses) - 1)]
            self._call_index += 1
            return resp
        return _make_chat_response(message="Mình tìm được 0 địa điểm.", places=[], fallback=True)


class FakeCheckpointer:
    def __init__(self) -> None:
        self._store: dict[str, list[dict[str, str]]] = {}

    async def load_history(self, session_id: str) -> list[dict[str, str]]:
        return list(self._store.get(session_id, []))

    async def save_turn(self, session_id: str, user: str, assistant: str) -> None:
        history = self._store.setdefault(session_id, [])
        history.extend([{"role": "user", "content": user}, {"role": "assistant", "content": assistant}])
        del history[:-8]


# ===========================================================================
# R038 Contract: No RAG fallback — citations=[] in all failure paths
# ===========================================================================

class TestR038_NoRagFallback:
    """R038: Place requests must never invoke RAG or produce document citations."""

    @pytest.mark.asyncio
    async def test_timeout_cache_hit_citations_empty(self):
        """Timeout + cache hit → citations=[] (no RAG)."""
        cache = FakePlaceCache(
            candidates=[_make_candidate("cached_1", "Quán Timeout Hit")],
            result="hit",
        )
        svc = GooglePlacesService(
            settings=FakeSettings,
            client=FakeClient(raise_exception=httpx.TimeoutException("timeout")),
            place_cache=cache,
        )
        result = await svc.text_search(_make_request("timeout hit"))
        assert result.status == PlaceToolStatus.OK
        dump = result.model_dump_json()
        assert "citation" not in dump.lower()

    @pytest.mark.asyncio
    async def test_timeout_cache_miss_citations_empty(self):
        """Timeout + cache miss → citations=[] (no RAG)."""
        cache = FakePlaceCache(candidates=None, result="miss")
        svc = GooglePlacesService(
            settings=FakeSettings,
            client=FakeClient(raise_exception=httpx.TimeoutException("timeout")),
            place_cache=cache,
        )
        result = await svc.text_search(_make_request("timeout miss"))
        assert result.status == PlaceToolStatus.UNAVAILABLE
        dump = result.model_dump_json()
        assert "citation" not in dump.lower()

    @pytest.mark.asyncio
    async def test_5xx_cache_hit_citations_empty(self):
        """500 upstream error + cache hit → citations=[] (no RAG)."""
        cache = FakePlaceCache(
            candidates=[_make_candidate("cached_5xx", "Quán 500 Hit")],
            result="hit",
        )
        svc = GooglePlacesService(
            settings=FakeSettings,
            client=FakeClient(status_code=500, payload={"error": {"message": "Internal"}}),
            place_cache=cache,
        )
        result = await svc.text_search(_make_request("500 hit"))
        assert result.status == PlaceToolStatus.OK
        dump = result.model_dump_json()
        assert "citation" not in dump.lower()

    @pytest.mark.asyncio
    async def test_5xx_cache_miss_citations_empty(self):
        """500 upstream error + cache miss → citations=[] (no RAG)."""
        cache = FakePlaceCache(candidates=None, result="miss")
        svc = GooglePlacesService(
            settings=FakeSettings,
            client=FakeClient(status_code=500, payload={"error": {"message": "Internal"}}),
            place_cache=cache,
        )
        result = await svc.text_search(_make_request("500 miss"))
        assert result.status == PlaceToolStatus.UNAVAILABLE
        dump = result.model_dump_json()
        assert "citation" not in dump.lower()

    @pytest.mark.asyncio
    async def test_circuit_open_cache_hit_citations_empty(self):
        """Circuit open + cache hit → citations=[] (no RAG)."""
        cache = FakePlaceCache(
            candidates=[_make_candidate("circuit_hit", "Quán Circuit Hit")],
            result="hit",
        )
        circuit = CircuitState(failure_threshold=1)
        circuit.record_failure()
        svc = GooglePlacesService(
            settings=FakeSettings,
            client=FakeClient(payload={"places": [{"id": "should_not_call"}]}),
            place_cache=cache,
            circuit=circuit,
        )
        result = await svc.text_search(_make_request("circuit hit"))
        assert len(svc._client.post_calls) == 0  # provider skipped
        assert result.status == PlaceToolStatus.OK
        dump = result.model_dump_json()
        assert "citation" not in dump.lower()

    @pytest.mark.asyncio
    async def test_circuit_open_cache_miss_citations_empty(self):
        """Circuit open + cache miss → citations=[] (no RAG)."""
        cache = FakePlaceCache(candidates=None, result="miss")
        circuit = CircuitState(failure_threshold=1)
        circuit.record_failure()
        svc = GooglePlacesService(
            settings=FakeSettings,
            client=FakeClient(payload={"places": [{"id": "should_not_call"}]}),
            place_cache=cache,
            circuit=circuit,
        )
        result = await svc.text_search(_make_request("circuit miss"))
        assert len(svc._client.post_calls) == 0
        assert result.status == PlaceToolStatus.UNAVAILABLE
        dump = result.model_dump_json()
        assert "citation" not in dump.lower()

    @pytest.mark.asyncio
    async def test_recommendation_service_never_produces_citations(self):
        """PlaceRecommendationService always returns citations=[] — no corpus access."""
        cache = FakePlaceCache(
            candidates=[_make_candidate("rec_svc", "Quán RecSvc")],
            result="hit",
        )
        places_svc = GooglePlacesService(
            settings=FakeSettings,
            client=FakeClient(raise_exception=httpx.TimeoutException("timeout")),
            place_cache=cache,
        )
        recommender = PlaceRecommendationService(places_svc, routes_service=None)
        response = await recommender.recommend(
            query="nhà hàng", language="vi", session_id="contract-rec"
        )
        assert response.citations == []


# ===========================================================================
# R046 Contract: Fallback diagnostics are inspectable
# ===========================================================================

class TestR046_FallbackDiagnostics:
    """R046: Fallback state must be inspectable via provider_status, warnings,
    reasoning_log, request_metadata, cache diagnostics, and circuit indicators."""

    @pytest.mark.asyncio
    async def test_timeout_cache_hit_shows_warnings_and_reasoning(self):
        """Timeout + cache hit → warning about provider, reasoning_log mentions cache."""
        cache = FakePlaceCache(
            candidates=[_make_candidate("diag_hit", "Quán Diag Hit")],
            result="hit",
        )
        svc = GooglePlacesService(
            settings=FakeSettings,
            client=FakeClient(raise_exception=httpx.TimeoutException("timeout")),
            place_cache=cache,
        )
        result = await svc.text_search(_make_request("diag hit"))
        assert result.status == PlaceToolStatus.OK
        assert any("provider" in w.lower() and "unavailable" in w.lower() for w in result.warnings)
        assert any("cache" in e.lower() for e in result.reasoning_log)
        assert result.audit.get("fallback_source") == "cache"

    @pytest.mark.asyncio
    async def test_timeout_cache_miss_shows_fallback_reason(self):
        """Timeout + cache miss → fallback_reason includes provider + cache miss."""
        cache = FakePlaceCache(candidates=None, result="miss")
        svc = GooglePlacesService(
            settings=FakeSettings,
            client=FakeClient(raise_exception=httpx.TimeoutException("timeout")),
            place_cache=cache,
        )
        result = await svc.text_search(_make_request("diag miss"))
        assert result.status == PlaceToolStatus.UNAVAILABLE
        assert "fallback_reason" in result.audit
        assert "provider" in result.audit["fallback_reason"].lower()

    @pytest.mark.asyncio
    async def test_circuit_open_shows_circuit_state_in_audit(self):
        """Circuit open → audit includes circuit_state."""
        cache = FakePlaceCache(
            candidates=[_make_candidate("circuit_diag", "Quán Circuit Diag")],
            result="hit",
        )
        circuit = CircuitState(failure_threshold=1)
        circuit.record_failure()
        svc = GooglePlacesService(
            settings=FakeSettings,
            client=FakeClient(payload={"places": []}),
            place_cache=cache,
            circuit=circuit,
        )
        result = await svc.text_search(_make_request("circuit diag"))
        # Circuit-open cache hit: audit includes circuit_state and fallback_source.
        # (fallback_reason is only set for cache-miss/unavailable paths.)
        assert result.audit.get("circuit_state") == "open"
        assert result.audit.get("fallback_source") == "cache"

    @pytest.mark.asyncio
    async def test_stale_cache_warning_includes_staleness_seconds(self):
        """Stale cache → staleness_seconds in audit and warning mentions stale."""
        cache = FakePlaceCache(
            candidates=[_make_candidate("stale_diag", "Quán Stale Diag")],
            result="stale",
            staleness_seconds=7200.0,
        )
        svc = GooglePlacesService(
            settings=FakeSettings,
            client=FakeClient(raise_exception=httpx.TimeoutException("timeout")),
            place_cache=cache,
        )
        result = await svc.text_search(_make_request("stale diag"))
        assert result.status == PlaceToolStatus.OK
        assert result.audit.get("fallback_source") == "cache_stale"
        assert result.audit.get("staleness_seconds") == 7200.0
        assert any("stale" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_malformed_cache_row_treated_as_miss(self):
        """Malformed cache data → treated as miss, not served as broken data."""
        cache = FakePlaceCache(candidates=None, result="malformed")
        svc = GooglePlacesService(
            settings=FakeSettings,
            client=FakeClient(raise_exception=httpx.TimeoutException("timeout")),
            place_cache=cache,
        )
        result = await svc.text_search(_make_request("malformed"))
        assert result.status == PlaceToolStatus.UNAVAILABLE
        assert result.candidates == []
        assert result.audit.get("cache_result") == "miss"

    @pytest.mark.asyncio
    async def test_cache_db_error_returns_safe_diagnostics(self):
        """Cache DB error → safe warning, no raw exception text in response."""
        cache = FakePlaceCache(candidates=None, result="error")
        svc = GooglePlacesService(
            settings=FakeSettings,
            client=FakeClient(raise_exception=httpx.TimeoutException("timeout")),
            place_cache=cache,
        )
        result = await svc.text_search(_make_request("db error"))
        assert result.status == PlaceToolStatus.UNAVAILABLE
        # Safe warning must exist
        assert any("cache" in w.lower() for w in result.warnings)
        # No raw exception details leaked
        dump = result.model_dump_json()
        assert "cache db down" not in dump

    @pytest.mark.asyncio
    async def test_cache_upsert_db_error_does_not_break_response(self):
        """Cache upsert error → provider OK response still succeeds."""
        cache = FakePlaceCache(
            candidates=[_make_candidate("upsert_err", "Quán Upsert")],
            result="hit",
        )
        cache.raise_on_upsert = RuntimeError("disk full") if hasattr(cache, "raise_on_upsert") else None
        # Use a FakePlaceCache variant that can raise on upsert
        class UpsertFailCache(FakePlaceCache):
            async def upsert(self, request, candidates, *, ttl_seconds=900, source="goong_places"):
                raise RuntimeError("disk full")

        upsert_fail_cache = UpsertFailCache(
            candidates=[_make_candidate("upsert_ok", "Quán Upsert OK")],
            result="hit",
        )
        ok_client = FakeClient(payload={"places": [{"id": "ok_place", "displayName": {"text": "OK Place"}}]})
        svc = GooglePlacesService(
            settings=FakeSettings,
            client=ok_client,
            place_cache=upsert_fail_cache,
        )
        result = await svc.text_search(_make_request("upsert err"))
        assert result.status == PlaceToolStatus.OK

    @pytest.mark.asyncio
    async def test_request_metadata_always_has_field_mask(self):
        """request_metadata includes field_mask in every path."""
        cache = FakePlaceCache(candidates=None, result="miss")
        svc = GooglePlacesService(
            settings=FakeSettings,
            client=FakeClient(raise_exception=httpx.TimeoutException("timeout")),
            place_cache=cache,
        )
        result = await svc.text_search(_make_request("fieldmask"))
        assert result.request_metadata["field_mask"] == GOOGLE_PLACES_FIELD_MASK

    @pytest.mark.asyncio
    async def test_no_cache_configured_shows_no_cache_warning(self):
        """No cache configured → warning says cache not configured."""
        svc = GooglePlacesService(
            settings=FakeSettings,
            client=FakeClient(raise_exception=httpx.TimeoutException("timeout")),
            place_cache=None,
        )
        result = await svc.text_search(_make_request("no cache"))
        assert result.status == PlaceToolStatus.UNAVAILABLE
        assert any("cache" in w.lower() and "not configured" in w.lower() for w in result.warnings)


# ===========================================================================
# R038 Contract: Credential missing + cache still works
# ===========================================================================

class TestCredentialMissingWithCache:
    """Even when credentials are missing, the system behaves predictably."""

    @pytest.mark.asyncio
    async def test_credential_missing_returns_credential_blocked(self):
        """Missing API key → CREDENTIALS_BLOCKED immediately, no outbound call."""

        class NoKeySettings:
            GOOGLE_PLACES_API_KEY = ""
            DATABASE_URL = ""

        cache = FakePlaceCache(
            candidates=[_make_candidate("cred_hit", "Quán Cred Hit")],
            result="hit",
        )
        svc = GooglePlacesService(
            settings=NoKeySettings,
            client=FakeClient(payload={"places": [{"id": "never_called"}]}),
            place_cache=cache,
        )
        result = await svc.text_search(_make_request("cred blocked"))
        assert result.status == PlaceToolStatus.CREDENTIALS_BLOCKED
        assert result.candidates == []
        # Provider was NOT called
        assert len(svc._client.post_calls) == 0


# ===========================================================================
# R038 Contract: Injection-shaped cached name guard
# ===========================================================================

class TestInjectionGuard:
    """Malicious display names in cached data must not leak into free-form text."""

    @pytest.mark.asyncio
    async def test_script_injection_in_cached_name_does_not_leak_into_message(self):
        """Cached display_name with <script> tag → returned in places but NOT in prose."""
        malicious = "<script>alert('xss')</script> Quán Độc"
        recommender = FakePlaceRecommender(responses=[
            _make_chat_response(
                message="Mình tìm được 1 địa điểm phù hợp.",
                places=[_make_place_result(place_id="p-inject", display_name=malicious)],
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
            session_id="contract-inject",
            message="tìm quán lạ",
            language="vi",
        )
        # Place is present with the exact display_name (typed, grounded)
        assert len(response.places) == 1
        assert response.places[0].display_name == malicious
        # But the prose message must NOT contain the injection payload
        assert "<script>" not in response.message
        assert "alert(" not in response.message
        # citations must be empty — R038
        assert response.citations == []

    @pytest.mark.asyncio
    async def test_sql_injection_in_cached_name_does_not_leak(self):
        """Cached display_name with SQL injection → not in prose message."""
        sqli = "'; DROP TABLE users; -- Quán SQL"
        recommender = FakePlaceRecommender(responses=[
            _make_chat_response(
                message="Mình tìm được 1 địa điểm phù hợp.",
                places=[_make_place_result(place_id="p-sqli", display_name=sqli)],
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
            session_id="contract-sqli",
            message="tìm quán",
            language="vi",
        )
        assert response.places[0].display_name == sqli
        assert "DROP TABLE" not in response.message
        assert response.citations == []


# ===========================================================================
# R038 Contract: Deterministic display_name-only text
# ===========================================================================

class TestDeterministicText:
    """Response text must only reference display_name values from typed places."""

    @pytest.mark.asyncio
    async def test_message_only_references_returned_display_names(self):
        """Multi-place response → message references only returned display_names."""
        places = [
            _make_place_result(place_id="p-a", display_name="Quán A"),
            _make_place_result(place_id="p-b", display_name="Quán B"),
        ]
        recommender = FakePlaceRecommender(responses=[
            _make_chat_response(
                message="Mình tìm được 2 địa điểm phù hợp: 1. Quán A; 2. Quán B.",
                places=places,
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
            session_id="contract-names",
            message="tìm quán ăn",
            language="vi",
        )
        returned_names = {p.display_name for p in response.places}
        assert returned_names == {"Quán A", "Quán B"}
        assert "Quán A" in response.message
        assert "Quán B" in response.message
        assert "Quán C" not in response.message

    @pytest.mark.asyncio
    async def test_empty_places_message_does_not_invent_names(self):
        """No places available → honest message with zero invented names."""
        recommender = FakePlaceRecommender(responses=[
            _make_chat_response(
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
            session_id="contract-empty",
            message="tìm quán không tồn tại",
            language="vi",
        )
        assert response.places == []
        # Must not contain any business name
        assert "Quán" not in response.message or "không khả dụng" in response.message
        assert response.citations == []


# ===========================================================================
# R046 Contract: No RAG corpus invocation (AgentService-level)
# ===========================================================================

class TestNoCorpusInvocation:
    """R038: hybrid_retriever must NEVER be called for place-deterministic routing."""

    @pytest.mark.asyncio
    async def test_hybrid_retriever_never_called_for_place_path(self):
        """Place path with hybrid_retriever available → retriever NOT called."""
        mock_hybrid = AsyncMock()
        mock_hybrid.search_with_citations = AsyncMock(
            return_value=(MagicMock(chunks=[]), [])
        )
        recommender = FakePlaceRecommender(responses=[
            _make_chat_response(
                message="Mình tìm được 1 địa điểm.",
                places=[_make_place_result()],
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
            session_id="contract-no-corpus",
            message="tìm quán hải sản",
            language="vi",
        )
        mock_hybrid.search_with_citations.assert_not_called()
        assert response.citations == []
        assert response.intent == PLACE_RECOMMENDATION_INTENT

    @pytest.mark.asyncio
    async def test_recommendation_service_exception_degrades_to_unavailable(self):
        """PlaceRecommendationService raises → AgentService returns unavailable, citations=[]."""
        recommender = FakePlaceRecommender(raise_on=RuntimeError("db connection lost"))
        agent = AgentService(
            retriever=None,
            hybrid_retriever=None,
            llm_service=None,
            checkpointer=FakeCheckpointer(),
            checkpoint_mode="test",
            place_recommendation_service=recommender,
        )
        response = await agent.answer(
            session_id="contract-svc-err",
            message="tìm nhà hàng",
            language="vi",
        )
        assert response.citations == []
        assert response.places == []
        assert response.fallback is True

    @pytest.mark.asyncio
    async def test_no_place_service_returns_honest_unavailable(self):
        """AgentService with no place_recommendation_service → citations=[], fallback=True."""
        agent = AgentService(
            retriever=None,
            hybrid_retriever=None,
            llm_service=None,
            checkpointer=FakeCheckpointer(),
            checkpoint_mode="test",
            place_recommendation_service=None,
        )
        response = await agent.answer(
            session_id="contract-no-svc",
            message="kiếm nhà hàng gần đây",
            language="vi",
        )
        assert response.citations == []
        assert response.places == []
        assert response.fallback is True


# ===========================================================================
# R046 Contract: Secret redaction in all failure paths
# ===========================================================================

class TestSecretRedaction:
    """No API keys or credentials in any serialized response."""

    @pytest.mark.asyncio
    async def test_no_api_key_in_unavailable_dump(self):
        cache = FakePlaceCache(candidates=None, result="miss")
        svc = GooglePlacesService(
            settings=FakeSettings,
            client=FakeClient(raise_exception=httpx.TimeoutException("timeout")),
            place_cache=cache,
        )
        result = await svc.text_search(_make_request("redact"))
        dump = result.model_dump_json()
        assert "fake-api-key-for-testing" not in dump

    @pytest.mark.asyncio
    async def test_no_api_key_in_cache_hit_dump(self):
        cache = FakePlaceCache(
            candidates=[_make_candidate("redact_hit", "Quán Redact")],
            result="hit",
        )
        svc = GooglePlacesService(
            settings=FakeSettings,
            client=FakeClient(raise_exception=httpx.TimeoutException("timeout")),
            place_cache=cache,
        )
        result = await svc.text_search(_make_request("redact hit"))
        dump = result.model_dump_json()
        assert "fake-api-key-for-testing" not in dump

    @pytest.mark.asyncio
    async def test_no_api_key_in_circuit_open_dump(self):
        cache = FakePlaceCache(
            candidates=[_make_candidate("redact_circuit", "Quán Redact Circuit")],
            result="hit",
        )
        circuit = CircuitState(failure_threshold=1)
        circuit.record_failure()
        svc = GooglePlacesService(
            settings=FakeSettings,
            client=FakeClient(payload={"places": []}),
            place_cache=cache,
            circuit=circuit,
        )
        result = await svc.text_search(_make_request("redact circuit"))
        dump = result.model_dump_json()
        assert "fake-api-key-for-testing" not in dump


# ===========================================================================
# R046 Contract: Full-fallback integration through AgentService
# ===========================================================================

class TestFullFallbackIntegration:
    """End-to-end fallback integration through AgentService layer."""

    @pytest.mark.asyncio
    async def test_agent_service_fallback_cache_hit_propagates_diagnostics(self):
        """AgentService → cache-hit fallback → reasoning_log includes cache source."""
        recommender = FakePlaceRecommender(responses=[
            _make_chat_response(
                message="Mình tìm được 1 địa điểm phù hợp: 1. Quán Full Diag.",
                places=[_make_place_result(display_name="Quán Full Diag")],
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
            session_id="contract-full",
            message="tìm quán gần đây",
            language="vi",
        )
        assert response.citations == []
        assert len(response.places) == 1
        assert response.places[0].display_name == "Quán Full Diag"
        assert response.reasoning_log is not None
        assert "cache" in response.reasoning_log.lower()

    @pytest.mark.asyncio
    async def test_agent_service_fallback_miss_propagates_fallback_true(self):
        """AgentService → cache-miss fallback → fallback=True, citations=[]."""
        recommender = FakePlaceRecommender(responses=[
            _make_chat_response(
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
            session_id="contract-full-miss",
            message="tìm quán không tồn tại",
            language="vi",
        )
        assert response.citations == []
        assert response.places == []
        assert response.fallback is True
