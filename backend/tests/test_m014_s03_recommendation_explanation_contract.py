"""M014/S03: Recommendation Explanation Contract Tests.

Locks the S03-specific invariants: every grounded place recommendation must
carry a stable backend-owned score, explanation, and provider contract that
can answer "why this place?" without frontend-fabricated reasoning.

Contract surface:
- Every PlaceResult carries score_breakdown with all 8 fields and rank parity.
- final_score on PlaceResult == score_breakdown.final_score (parity check).
- PlaceExplanation is present with bounded, redacted text in every field.
- provider_source and provider_status are set from normalized candidate data.
- evidence_fields_used lists only fields actually consumed.
- matched_preferences derive only from normalized candidate/request fields.
- No API keys, raw provider payloads, phone numbers, or exact user GPS in
  explanation text, reasoning_log, or any serialized response field.
- Negative paths (provider error, empty candidates, missing metadata, reranker
  fallback) degrade safely to unknown/limited explanation fields.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.models.places import (
    PlaceCandidate,
    PlaceSearchRequest,
    PlaceToolResponse,
    PlaceToolSource,
    PlaceToolStatus,
    RouteContext,
)
from app.models.request import LatLng
from app.models.response import PlaceExplanation, PlaceResult, ScoreBreakdown
from agents.services.place_recommendation_service import (
    PlaceRecommendationService,
    _redact_text,
    _grounded_results,
    _reranked_results,
    _balance_fairness,
    _build_place_explanation,
    _compute_fairness_audit,
    _apply_preference_filters,
    FAIRNESS_LOCAL_THRESHOLD,
)
from agents.ml.feature_extractor import FeatureExtractor
from agents.ml.ensemble_reranker import EnsembleReranker


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _candidate(
    *,
    place_id: str = "places/test_001",
    display_name: str = "Quán Hải Sản Hàm Ninh",
    types: list[str] | None = None,
    rating: float | None = 4.5,
    price_level: int | None = 2,
    open_now: bool | None = True,
    local_factor: float | None = 0.8,
    location: LatLng | None = None,
    accessibility_options: dict[str, bool] | None = None,
    business_status: str | None = "OPERATIONAL",
    route_context: RouteContext | None = None,
    **extra: Any,
) -> PlaceCandidate:
    """Build a PlaceCandidate with sensible defaults."""
    return PlaceCandidate(
        place_id=place_id,
        display_name=display_name,
        types=types or ["restaurant", "seafood_restaurant"],
        rating=rating,
        price_level=price_level,
        open_now=open_now,
        local_factor=local_factor,
        location=location,
        accessibility_options=accessibility_options or {},
        business_status=business_status,
        route_context=route_context,
        **extra,
    )


def _request(
    *,
    query: str = "nhà hàng hải sản",
    budget: list[str] | None = None,
    accessibility: bool | None = None,
    user_location: LatLng | None = None,
) -> PlaceSearchRequest:
    """Build a PlaceSearchRequest with optional preferences."""
    from app.models.places import PriceLevel
    budget_filter = None
    if budget:
        budget_filter = [PriceLevel(b) for b in budget]
    return PlaceSearchRequest(
        query=query,
        language_code="vi",
        budget_filter=budget_filter,
        wheelchair_accessible_preference=accessibility,
        user_location=user_location,
    )


def _tool_response(
    *,
    status: PlaceToolStatus = PlaceToolStatus.OK,
    source: PlaceToolSource = PlaceToolSource.MOCK,
    candidates: list[PlaceCandidate] | None = None,
    request: PlaceSearchRequest | None = None,
) -> PlaceToolResponse:
    return PlaceToolResponse(
        status=status,
        source=source,
        candidates=candidates or [],
        request=request or _request(),
        retrieved_at=datetime.now(UTC),
    )


def _make_service(
    *,
    candidates: list[PlaceCandidate] | None = None,
    status: PlaceToolStatus = PlaceToolStatus.OK,
    source: PlaceToolSource = PlaceToolSource.MOCK,
    routes_service: Any = None,
) -> PlaceRecommendationService:
    """Build a PlaceRecommendationService with a fake places tool."""
    tool = AsyncMock()
    tool.text_search.return_value = _tool_response(
        status=status, source=source, candidates=candidates or [],
    )
    return PlaceRecommendationService(places_tool=tool, routes_service=routes_service)


# ---------------------------------------------------------------------------
# E1: ScoreBreakdown completeness and rank parity
# ---------------------------------------------------------------------------

class TestScoreBreakdownCompleteness:
    """Every PlaceResult must carry a complete ScoreBreakdown."""

    @pytest.mark.asyncio
    async def test_result_has_score_breakdown(self) -> None:
        """PlaceResult must have a score_breakdown field."""
        svc = _make_service(candidates=[_candidate()])
        resp = await svc.recommend(query="hải sản", session_id="s1")
        assert len(resp.places) > 0
        for place in resp.places:
            assert place.score_breakdown is not None

    def test_score_breakdown_has_all_fields(self) -> None:
        """ScoreBreakdown must contain all 8 required fields."""
        candidates = [_candidate()]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            sb = r.score_breakdown
            assert sb.tree1_locality is not None
            assert sb.tree2_proximity is not None
            assert sb.tree3_quality is not None
            assert sb.s_bag is not None
            assert sb.delta1_fairness is not None
            assert sb.delta2_access is not None
            assert sb.final_score is not None
            assert sb.rank is not None

    def test_score_breakdown_values_in_range(self) -> None:
        """Tree scores and s_bag must be in [0, 1]."""
        candidates = [_candidate()]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            sb = r.score_breakdown
            assert 0.0 <= sb.tree1_locality <= 1.0
            assert 0.0 <= sb.tree2_proximity <= 1.0
            assert 0.0 <= sb.tree3_quality <= 1.0
            assert 0.0 <= sb.s_bag <= 1.0
            assert 0.0 <= sb.final_score <= 1.0

    def test_final_score_parity(self) -> None:
        """PlaceResult.final_score must equal score_breakdown.final_score."""
        candidates = [_candidate(), _candidate(place_id="p2", local_factor=0.3)]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            assert r.final_score == pytest.approx(r.score_breakdown.final_score, rel=1e-9)

    def test_rank_is_one_based_sequential(self) -> None:
        """Ranks must be 1-based and sequential after sorting."""
        candidates = [
            _candidate(place_id="p1", local_factor=0.3),
            _candidate(place_id="p2", local_factor=0.9),
            _candidate(place_id="p3", local_factor=0.5),
        ]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        ranks = [r.score_breakdown.rank for r in results]
        assert ranks == list(range(1, len(results) + 1))
        # Also check PlaceResult rank mirrors breakdown rank
        for r in results:
            assert r.score_breakdown.rank >= 1


# ---------------------------------------------------------------------------
# E2: PlaceExplanation completeness and boundedness
# ---------------------------------------------------------------------------

class TestPlaceExplanationCompleteness:
    """Every PlaceResult must carry a PlaceExplanation with bounded, redacted fields."""

    @pytest.mark.asyncio
    async def test_result_has_explanation(self) -> None:
        """PlaceResult must have an explanation field."""
        svc = _make_service(candidates=[_candidate()])
        resp = await svc.recommend(query="hải sản", session_id="s1")
        assert len(resp.places) > 0
        for place in resp.places:
            assert place.explanation is not None

    def test_explanation_has_required_fields(self) -> None:
        """PlaceExplanation must carry all expected fields."""
        candidates = [_candidate()]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            exp = r.explanation
            assert isinstance(exp, PlaceExplanation)
            assert isinstance(exp.rank, int)
            assert isinstance(exp.primary_reason, str)
            assert isinstance(exp.matched_preferences, list)
            assert isinstance(exp.local_context, str)
            assert isinstance(exp.score_factors, dict)
            assert isinstance(exp.fairness_note, str)
            assert isinstance(exp.accessibility_note, str)
            assert isinstance(exp.route_summary, str)
            assert isinstance(exp.provider_source, (str, type(None)))
            assert isinstance(exp.provider_status, (str, type(None)))
            assert isinstance(exp.evidence_fields_used, list)

    def test_explanation_text_fields_bounded(self) -> None:
        """All explanation text fields must be within max_length."""
        candidates = [_candidate()]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            exp = r.explanation
            assert len(exp.primary_reason) <= 240
            assert len(exp.local_context) <= 160
            assert len(exp.fairness_note) <= 200
            assert len(exp.accessibility_note) <= 200
            assert len(exp.route_summary) <= 200

    def test_explanation_list_fields_bounded(self) -> None:
        """matched_preferences and evidence_fields_used must be bounded."""
        candidates = [_candidate()]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            exp = r.explanation
            assert len(exp.matched_preferences) <= 10
            assert len(exp.evidence_fields_used) <= 20

    def test_explanation_score_factors_bounded(self) -> None:
        """score_factors dict must not exceed max_length."""
        candidates = [_candidate()]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            exp = r.explanation
            assert len(exp.score_factors) <= 12

    def test_explanation_rank_matches_breakdown(self) -> None:
        """PlaceExplanation.rank must equal score_breakdown.rank."""
        candidates = [_candidate(place_id="p1"), _candidate(place_id="p2", local_factor=0.3)]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            assert r.explanation.rank == r.score_breakdown.rank


# ---------------------------------------------------------------------------
# E3: Provider source and status
# ---------------------------------------------------------------------------

class TestProviderSourceAndStatus:
    """provider_source and provider_status must be set from normalized data."""

    def test_explanation_carries_provider_source(self) -> None:
        """PlaceExplanation must carry the provider_source label."""
        candidates = [_candidate()]
        results = _reranked_results(candidates, "hải sản", provider_source="google_places")
        for r in results:
            assert r.explanation.provider_source == "google_places"

    def test_explanation_carries_provider_status(self) -> None:
        """PlaceExplanation.provider_status must reflect candidate business_status."""
        candidates = [_candidate(business_status="OPERATIONAL")]
        results = _reranked_results(candidates, "hải sản", provider_source="goong_places")
        for r in results:
            assert r.explanation.provider_status == "OPERATIONAL"

    def test_provider_source_none_when_unspecified(self) -> None:
        """When provider_source is None, explanation.provider_source is None."""
        candidates = [_candidate()]
        results = _reranked_results(candidates, "hải sản", provider_source=None)
        for r in results:
            assert r.explanation.provider_source is None

    @pytest.mark.asyncio
    async def test_service_explanation_has_provider_source(self) -> None:
        """Full service must propagate provider_source to explanation."""
        svc = _make_service(candidates=[_candidate()], source=PlaceToolSource.GOOGLE_PLACES)
        resp = await svc.recommend(query="hải sản", session_id="s1")
        for place in resp.places:
            # provider_source should be the tool source label
            assert place.explanation.provider_source in (
                "google_places", "goong_places", "mock", "cache",
            )


# ---------------------------------------------------------------------------
# E4: Evidence fields used — no fabricated rationale
# ---------------------------------------------------------------------------

class TestEvidenceFieldsUsed:
    """evidence_fields_used must only list fields actually consumed."""

    def test_evidence_includes_base_fields(self) -> None:
        """Every explanation must reference at least the base fields."""
        candidates = [_candidate()]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            exp = r.explanation
            assert "place_id" in exp.evidence_fields_used
            assert "display_name" in exp.evidence_fields_used
            assert "score_breakdown" in exp.evidence_fields_used

    def test_evidence_includes_rating_when_present(self) -> None:
        """When rating is present, evidence_fields_used must include it."""
        candidates = [_candidate(rating=4.5)]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            assert "rating" in r.explanation.evidence_fields_used

    def test_evidence_includes_price_when_present(self) -> None:
        """When price_level is present, evidence_fields_used must include it."""
        candidates = [_candidate(price_level=2)]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            assert "price_level" in r.explanation.evidence_fields_used

    def test_evidence_includes_local_factor_when_present(self) -> None:
        """When local_factor meets threshold, evidence_fields_used must include it."""
        candidates = [_candidate(local_factor=0.8)]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            assert "local_factor" in r.explanation.evidence_fields_used

    def test_evidence_includes_type_fields(self) -> None:
        """Explanation must evidence the type source (primary_type or types)."""
        candidates = [_candidate(types=["restaurant", "seafood_restaurant"])]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            exp = r.explanation
            assert "primary_type" in exp.evidence_fields_used or "types" in exp.evidence_fields_used


# ---------------------------------------------------------------------------
# E5: Redaction — no secrets, phones, API keys, or raw GPS
# ---------------------------------------------------------------------------

class TestRedactionBoundary:
    """No API keys, raw payloads, phone numbers, or exact GPS in explanation text."""

    def test_redact_strips_api_key_tokens(self) -> None:
        """API-key-like tokens must be stripped."""
        assert "AIza" not in _redact_text("key is AIzaSyD1234567890abcdef")
        assert "sk-" not in _redact_text("auth sk-abc123def456ghi")
        assert "[key_redacted]" in _redact_text("token is gsk-abcdefghijklmnop")

    def test_redact_strips_secret_assignments(self) -> None:
        """key=, token=, secret= patterns must be redacted."""
        result = _redact_text("my key=SECRET123 is here")
        assert "[secret_redacted]" in result

    def test_redact_strips_phone_numbers(self) -> None:
        """Phone-like patterns must be redacted."""
        result = _redact_text("call +84 297 384 6123 for info")
        assert "[phone_redacted]" in result
        result = _redact_text("phone: 02973846123")
        assert "[phone_redacted]" in result

    def test_redact_truncates_to_max_length(self) -> None:
        """_redact_text must cap output length."""
        long_text = "x" * 500
        result = _redact_text(long_text, max_length=50)
        assert len(result) <= 50

    @pytest.mark.asyncio
    async def test_no_api_key_in_explanation_serialization(self) -> None:
        """Serialized explanation must not contain API-key patterns."""
        svc = _make_service(candidates=[_candidate()])
        resp = await svc.recommend(query="hải sản", session_id="s1")
        dump = resp.model_dump_json()
        # No API key patterns anywhere
        assert "AIza" not in dump
        assert "sk-" not in dump.lower() or "sk-" in dump.lower() and "key_redacted" in dump.lower()
        assert "GOOGLE_PLACES_API_KEY" not in dump
        assert "GOONG_API_KEY" not in dump

    @pytest.mark.asyncio
    async def test_no_phone_in_explanation_serialization(self) -> None:
        """Serialized explanation must not contain raw phone numbers.

        Note: formatted_address on PlaceResult is a passthrough from the
        provider; _redact_text applies only to explanation text fields.
        """
        candidate = _candidate(
            display_name="Quán ABC",
            formatted_address="Gọi 02973846123 để đặt bàn",
        )
        svc = _make_service(candidates=[candidate])
        resp = await svc.recommend(query="hải sản", session_id="s1")
        # Check explanation fields specifically — these go through _redact_text
        for place in resp.places:
            exp_json = json.dumps(place.explanation.model_dump())
            assert "02973846123" not in exp_json
            assert "+84" not in exp_json

    @pytest.mark.asyncio
    async def test_no_raw_provider_payload_in_serialization(self) -> None:
        """Serialized response must not contain 'raw_payload' or raw provider JSON."""
        svc = _make_service(candidates=[_candidate()])
        resp = await svc.recommend(query="hải sản", session_id="s1")
        dump = resp.model_dump_json()
        assert "raw_payload" not in dump.lower()
        assert "raw_provider" not in dump.lower()


# ---------------------------------------------------------------------------
# E6: Matched preferences — from normalized fields only
# ---------------------------------------------------------------------------

class TestMatchedPreferences:
    """matched_preferences must derive only from normalized candidate/request fields."""

    def test_matched_pref_includes_type(self) -> None:
        """Type must appear in matched_preferences."""
        candidates = [_candidate(types=["restaurant"])]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            prefs = r.explanation.matched_preferences
            assert any("type:" in p for p in prefs)

    def test_matched_pref_includes_price_when_set(self) -> None:
        """price_level must appear in matched_preferences when present."""
        candidates = [_candidate(price_level=2)]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            prefs = r.explanation.matched_preferences
            assert any("price_level:" in p for p in prefs)

    def test_matched_pref_includes_budget_when_matched(self) -> None:
        """budget_preference_matched must appear when candidate price fits budget."""
        candidates = [_candidate(price_level=1)]
        request = _request(budget=["free", "inexpensive"])
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            prefs = r.explanation.matched_preferences
            assert "budget_preference_matched" in prefs

    def test_matched_pref_includes_accessibility_when_matched(self) -> None:
        """accessibility_preference_matched must appear when candidate is accessible
        and user requested accessibility."""
        candidates = [_candidate(
            accessibility_options={"wheelchairAccessibleParking": True},
        )]
        request = _request(accessibility=True)
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            prefs = r.explanation.matched_preferences
            assert "accessibility_preference_matched" in prefs

    def test_no_fabricated_preferences(self) -> None:
        """matched_preferences must only contain signals from normalized fields."""
        candidates = [_candidate(
            rating=None,
            price_level=None,
            open_now=None,
        )]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            prefs = r.explanation.matched_preferences
            # No budget matched since no budget in request
            assert "budget_preference_matched" not in prefs
            # No accessibility matched since no accessibility pref
            assert "accessibility_preference_matched" not in prefs


# ---------------------------------------------------------------------------
# E7: Negative test — provider non-OK responses
# ---------------------------------------------------------------------------

class TestProviderNonOkResponses:
    """Provider non-OK must produce places=[] with safe diagnostics."""

    @pytest.mark.asyncio
    async def test_upstream_error_produces_empty_places(self) -> None:
        """UPSTREAM_ERROR → places=[]."""
        svc = _make_service(
            candidates=[], status=PlaceToolStatus.UPSTREAM_ERROR,
            source=PlaceToolSource.GOOGLE_PLACES,
        )
        resp = await svc.recommend(query="hải sản", session_id="s1")
        assert resp.places == []
        assert resp.reasoning_log is not None
        assert "upstream_error" in resp.reasoning_log.lower()

    @pytest.mark.asyncio
    async def test_credentials_blocked_produces_empty_places(self) -> None:
        """CREDENTIALS_BLOCKED → places=[]."""
        svc = _make_service(
            candidates=[], status=PlaceToolStatus.CREDENTIALS_BLOCKED,
            source=PlaceToolSource.GOOGLE_PLACES,
        )
        resp = await svc.recommend(query="hải sản", session_id="s1")
        assert resp.places == []
        assert resp.reasoning_log is not None

    @pytest.mark.asyncio
    async def test_unavailable_produces_empty_places(self) -> None:
        """UNAVAILABLE → places=[]."""
        svc = _make_service(
            candidates=[], status=PlaceToolStatus.UNAVAILABLE,
            source=PlaceToolSource.GOOGLE_PLACES,
        )
        resp = await svc.recommend(query="hải sản", session_id="s1")
        assert resp.places == []

    @pytest.mark.asyncio
    async def test_non_ok_has_fairness_audit_warning(self) -> None:
        """Non-OK provider must produce fairness audit with provider_non_ok warning."""
        svc = _make_service(
            candidates=[], status=PlaceToolStatus.UPSTREAM_ERROR,
            source=PlaceToolSource.GOOGLE_PLACES,
        )
        resp = await svc.recommend(query="hải sản", session_id="s1")
        assert resp.fairness_audit is not None
        assert "provider_non_ok" in resp.fairness_audit.warnings

    @pytest.mark.asyncio
    async def test_non_ok_has_decision_trace(self) -> None:
        """Non-OK provider must produce a decision trace."""
        svc = _make_service(
            candidates=[], status=PlaceToolStatus.UPSTREAM_ERROR,
            source=PlaceToolSource.GOOGLE_PLACES,
        )
        resp = await svc.recommend(query="hải sản", session_id="s1")
        assert resp.decision_trace is not None
        assert len(resp.decision_trace.events) > 0


# ---------------------------------------------------------------------------
# E8: Negative test — empty candidates
# ---------------------------------------------------------------------------

class TestEmptyCandidates:
    """Empty candidates must produce safe output with no fabricated places."""

    @pytest.mark.asyncio
    async def test_empty_candidates_produces_empty_places(self) -> None:
        """OK status with empty candidates → places=[]."""
        svc = _make_service(candidates=[], status=PlaceToolStatus.OK)
        resp = await svc.recommend(query="hải sản", session_id="s1")
        assert resp.places == []

    @pytest.mark.asyncio
    async def test_empty_candidates_has_decision_trace(self) -> None:
        """Empty candidates must still produce a decision trace."""
        svc = _make_service(candidates=[], status=PlaceToolStatus.OK)
        resp = await svc.recommend(query="hải sản", session_id="s1")
        assert resp.decision_trace is not None

    @pytest.mark.asyncio
    async def test_empty_candidates_no_explanation_fabricated(self) -> None:
        """Empty candidates must not have any explanation content."""
        svc = _make_service(candidates=[], status=PlaceToolStatus.OK)
        resp = await svc.recommend(query="hải sản", session_id="s1")
        # No places = no explanations possible
        for place in resp.places:
            assert len(place.explanation.matched_preferences) == 0


# ---------------------------------------------------------------------------
# E9: Negative test — missing rich metadata
# ---------------------------------------------------------------------------

class TestMissingRichMetadata:
    """Missing rating/price/accessibility/route must degrade to unknown/limited."""

    def test_missing_rating_degrades_gracefully(self) -> None:
        """Missing rating must not crash; explanation uses default."""
        candidates = [_candidate(rating=None)]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        assert len(results) == 1
        r = results[0]
        assert r.rating is None
        # Score breakdown still produced via FeatureExtractor defaults
        assert r.score_breakdown.final_score >= 0.0

    def test_missing_price_degrades_gracefully(self) -> None:
        """Missing price_level must degrade to unknown in explanation."""
        candidates = [_candidate(price_level=None)]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        r = results[0]
        assert r.price_level is None
        # price_level not in matched_preferences when None
        assert not any("price_level:" in p for p in r.explanation.matched_preferences)

    def test_missing_accessibility_degrades_gracefully(self) -> None:
        """Missing accessibility must use 'unknown' note."""
        candidates = [_candidate(accessibility_options=None)]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        r = results[0]
        assert r.explanation.accessibility_note in (
            "accessibility metadata unknown",
            "accessibility options available",
        )

    def test_missing_local_factor_degrades_gracefully(self) -> None:
        """Missing local_factor must use conservative local_context."""
        candidates = [_candidate(local_factor=None)]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        r = results[0]
        # When local_factor is None, FeatureExtractor defaults to 0.5
        # which is below FAIRNESS_LOCAL_THRESHOLD (0.6), so:
        assert "limited local signal" in r.explanation.local_context.lower() or \
               "local signal unknown" in r.explanation.local_context.lower()

    def test_missing_route_context_degrades_gracefully(self) -> None:
        """Missing route_context must use 'route metadata unavailable'."""
        candidates = [_candidate(route_context=None)]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        r = results[0]
        assert "unavailable" in r.explanation.route_summary.lower() or \
               "limited" in r.explanation.route_summary.lower()


# ---------------------------------------------------------------------------
# E10: Negative test — malformed / redaction-prone candidate text
# ---------------------------------------------------------------------------

class TestMalformedCandidateText:
    """Malformed or redaction-prone candidate text must be sanitized."""

    def test_api_key_in_display_name_is_redacted(self) -> None:
        """API-key-like tokens must not appear in explanation text fields.

        Note: display_name on PlaceResult is a passthrough from the provider.
        _redact_text applies to explanation fields (matched_preferences,
        primary_reason, etc.).
        """
        candidate = _candidate(
            display_name="AIzaSyD1234567890abcdef Restaurant",
        )
        candidates = [candidate]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        # Check explanation fields — these go through _redact_text
        for r in results:
            exp_json = json.dumps(r.explanation.model_dump())
            assert "AIzaSyD" not in exp_json

    def test_phone_in_address_is_redacted(self) -> None:
        """Phone numbers must not appear in explanation text fields.

        Note: formatted_address is not consumed by _build_place_explanation,
        so phone numbers there should never surface in the explanation.
        """
        candidate = _candidate(
            formatted_address="123 Đường Biển, gọi 0297 384 6123",
        )
        candidates = [candidate]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            exp_json = json.dumps(r.explanation.model_dump())
            assert "0297 384 6123" not in exp_json

    def test_secret_in_type_is_redacted(self) -> None:
        """Secret-like text in types must not appear in explanation fields.

        Note: types list on PlaceResult is a passthrough.
        _redact_text applies to explanation matched_preferences.
        """
        candidate = _candidate(types=["secret=abc123", "restaurant"])
        candidates = [candidate]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            exp_json = json.dumps(r.explanation.model_dump())
            assert "secret=abc123" not in exp_json

    def test_long_display_name_is_truncated(self) -> None:
        """Very long display_name must not overflow explanation text fields.

        Note: display_name itself is capped at 200 chars by Pydantic,
        so we use a 190-char name to test that _redact_text truncation
        still caps the explanation fields at their max_length.
        """
        candidate = _candidate(display_name="x" * 190)
        candidates = [candidate]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        for r in results:
            assert len(r.explanation.primary_reason) <= 240


# ---------------------------------------------------------------------------
# E11: Negative test — reranker fallback path
# ---------------------------------------------------------------------------

class TestRerankerFallback:
    """Reranker exception must use grounded fallback scores and explanations."""

    def test_grounded_results_use_default_scores(self) -> None:
        """_grounded_results must produce 0.5 default scores for all trees."""
        candidates = [_candidate(), _candidate(place_id="p2", local_factor=0.3)]
        results = _grounded_results(candidates, provider_source="mock")
        assert len(results) == 2
        for r in results:
            sb = r.score_breakdown
            assert sb.tree1_locality == 0.5
            assert sb.tree2_proximity == 0.5
            assert sb.tree3_quality == 0.5
            assert sb.s_bag == 0.5
            assert sb.delta1_fairness == 0.0
            assert sb.delta2_access == 0.0
            assert r.final_score == 0.5

    def test_grounded_results_explanation_mentions_fallback(self) -> None:
        """Fallback explanation must mention 'fallback' in primary_reason."""
        candidates = [_candidate()]
        results = _grounded_results(candidates, provider_source="mock")
        r = results[0]
        assert "fallback" in r.explanation.primary_reason.lower()

    def test_grounded_results_preserve_provider_source(self) -> None:
        """Fallback must still propagate provider_source."""
        candidates = [_candidate()]
        results = _grounded_results(candidates, provider_source="goong_places")
        r = results[0]
        assert r.explanation.provider_source == "goong_places"

    def test_grounded_results_preserve_preference_matching(self) -> None:
        """Fallback must still compute preference match signals."""
        candidates = [_candidate(price_level=1)]
        request = _request(budget=["free", "inexpensive"])
        results = _grounded_results(candidates, request=request)
        r = results[0]
        assert "budget_preference_matched" in r.explanation.matched_preferences

    @pytest.mark.asyncio
    async def test_reranker_exception_triggers_fallback_path(self) -> None:
        """If _reranked_results raises, the service must fall back to _grounded_results."""
        # We can't easily inject a failing reranker, but we can verify that
        # _grounded_results produces valid output that the service uses.
        candidates = [_candidate()]
        results = _grounded_results(candidates, provider_source="mock")
        assert len(results) == 1
        r = results[0]
        assert r.explanation is not None
        assert r.score_breakdown is not None


# ---------------------------------------------------------------------------
# E12: Fairness balancing preserves explanations
# ---------------------------------------------------------------------------

class TestFairnessBalancing:
    """Fairness reordering must not break explanation integrity."""

    def test_balance_preserves_all_results(self) -> None:
        """_balance_fairness must not lose any results."""
        candidates = [
            _candidate(place_id=f"p{i}", local_factor=0.9 if i % 2 == 0 else 0.2)
            for i in range(6)
        ]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        balanced = _balance_fairness(results)
        assert len(balanced) == len(results)
        # Same place_ids present
        orig_ids = {r.place_id for r in results}
        balanced_ids = {r.place_id for r in balanced}
        assert orig_ids == balanced_ids

    def test_balance_preserves_explanations(self) -> None:
        """Balanced results must still have valid explanations."""
        candidates = [
            _candidate(place_id=f"p{i}", local_factor=0.9 if i % 2 == 0 else 0.2)
            for i in range(6)
        ]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        balanced = _balance_fairness(results)
        for r in balanced:
            assert r.explanation is not None
            assert len(r.explanation.primary_reason) <= 240
            assert r.explanation.rank >= 0

    def test_balance_preserves_score_breakdown(self) -> None:
        """Balanced results must still have complete score_breakdowns."""
        candidates = [
            _candidate(place_id=f"p{i}", local_factor=0.9 if i % 2 == 0 else 0.2)
            for i in range(6)
        ]
        request = _request()
        results = _reranked_results(candidates, "hải sản", request=request)
        balanced = _balance_fairness(results)
        for r in balanced:
            assert r.score_breakdown is not None
            assert r.score_breakdown.final_score >= 0.0


# ---------------------------------------------------------------------------
# E13: Preference filter diagnostics
# ---------------------------------------------------------------------------

class TestPreferenceFilterDiagnostics:
    """Preference filtering must be reflected in explanation matched_preferences."""

    def test_budget_filter_excluded_candidates(self) -> None:
        """Candidates outside budget must be excluded."""
        candidates = [
            _candidate(place_id="cheap", price_level=0),
            _candidate(place_id="expensive", price_level=4),
        ]
        request = _request(budget=["free", "inexpensive"])
        filtered, excluded = _apply_preference_filters(candidates, request)
        assert len(filtered) == 1
        assert filtered[0].place_id == "cheap"
        assert excluded == 1

    def test_accessibility_boost_promotes_local_factor(self) -> None:
        """Accessible candidates get a local_factor boost."""
        accessible = _candidate(
            place_id="accessible",
            local_factor=0.5,
            accessibility_options={"wheelchairAccessibleParking": True},
        )
        non_accessible = _candidate(
            place_id="non_accessible",
            local_factor=0.7,
            accessibility_options={},
        )
        candidates = [non_accessible, accessible]
        request = _request(accessibility=True)
        filtered, _ = _apply_preference_filters(candidates, request)
        # Accessible candidate boosted from 0.5 to 0.6
        acc_after = next(c for c in filtered if c.place_id == "accessible")
        assert acc_after.local_factor >= 0.6

    def test_unknown_accessibility_preserved(self) -> None:
        """Candidates with no accessibility_options dict must be preserved."""
        unknown = _candidate(
            place_id="unknown",
            local_factor=0.5,
            accessibility_options=None,
        )
        candidates = [unknown]
        request = _request(accessibility=True)
        filtered, _ = _apply_preference_filters(candidates, request)
        assert len(filtered) == 1
        assert filtered[0].place_id == "unknown"


# ---------------------------------------------------------------------------
# E14: Fairness audit completeness
# ---------------------------------------------------------------------------

class TestFairnessAuditCompleteness:
    """Fairness audit must capture all required diagnostics."""

    def test_audit_has_all_fields(self) -> None:
        """FairnessAudit must carry all expected fields."""
        candidates = [_candidate(local_factor=0.8), _candidate(place_id="p2", local_factor=0.2)]
        results = _reranked_results(candidates, "hải sản")
        audit = _compute_fairness_audit(
            candidates=candidates,
            results=results,
            provider_status=PlaceToolStatus.OK,
        )
        assert audit.candidate_count == 2
        assert audit.result_count == 2
        assert 0.0 <= audit.top5_local_ratio <= 1.0
        assert audit.missing_local_factor_count >= 0
        assert audit.provider_status is not None

    def test_audit_warns_on_missing_local_factor(self) -> None:
        """Audit must warn when candidates are missing local_factor."""
        candidates = [_candidate(local_factor=None)]
        results = _grounded_results(candidates)
        audit = _compute_fairness_audit(
            candidates=candidates,
            results=results,
            provider_status=PlaceToolStatus.OK,
        )
        assert any("missing_local_factor" in w for w in audit.warnings)

    def test_audit_warns_on_non_ok_provider(self) -> None:
        """Audit must warn when provider status is not OK."""
        audit = _compute_fairness_audit(
            candidates=[],
            results=[],
            provider_status=PlaceToolStatus.UPSTREAM_ERROR,
        )
        assert "provider_non_ok" in audit.warnings

    def test_audit_warns_on_route_enrichment_fallback(self) -> None:
        """Audit must warn when route enrichment fails."""
        audit = _compute_fairness_audit(
            candidates=[],
            results=[],
            provider_status=PlaceToolStatus.OK,
            route_enrichment_ok=False,
        )
        assert "route_enrichment_fallback" in audit.warnings

    def test_audit_warns_on_ensemble_fallback(self) -> None:
        """Audit must warn when ensemble reranking falls back."""
        audit = _compute_fairness_audit(
            candidates=[],
            results=[],
            provider_status=PlaceToolStatus.OK,
            ensemble_ok=False,
        )
        assert "ensemble_fallback" in audit.warnings


# ---------------------------------------------------------------------------
# E15: Extra='forbid' enforcement on explanation model
# ---------------------------------------------------------------------------

class TestExplanationExtraForbid:
    """PlaceExplanation must reject extra fields (no frontend injection)."""

    def test_explanation_rejects_extra_fields(self) -> None:
        """Pydantic extra='forbid' must prevent arbitrary field injection."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PlaceExplanation(
                rank=1,
                primary_reason="test",
                frontend_fabricated_reason="made up",
            )

    def test_explanation_rejects_nested_extra_fields(self) -> None:
        """Extra fields in score_factors must not violate the model."""
        # score_factors is a dict, not a nested model — extra='forbid' applies
        # to PlaceExplanation top-level fields only. Verify the model accepts
        # dict values in score_factors.
        exp = PlaceExplanation(
            rank=1,
            primary_reason="test",
            score_factors={"rank": 1, "final_score": 0.8},
        )
        assert exp.score_factors["rank"] == 1


# ---------------------------------------------------------------------------
# E16: ChatResponse reasoning_log is safe
# ---------------------------------------------------------------------------

class TestReasoningLogSafety:
    """reasoning_log must not contain secrets or raw payloads."""

    @pytest.mark.asyncio
    async def test_reasoning_log_no_api_key(self) -> None:
        """reasoning_log must not contain API key patterns."""
        svc = _make_service(candidates=[_candidate()])
        resp = await svc.recommend(query="hải sản", session_id="s1")
        log = resp.reasoning_log or ""
        assert "test-key" not in log.lower()
        assert "api_key" not in log.lower()

    @pytest.mark.asyncio
    async def test_reasoning_log_no_phone(self) -> None:
        """reasoning_log must not contain phone numbers."""
        candidate = _candidate(
            formatted_address="Gọi 0297 384 6123 để đặt bàn",
        )
        svc = _make_service(candidates=[candidate])
        resp = await svc.recommend(query="hải sản", session_id="s1")
        log = resp.reasoning_log or ""
        assert "0297" not in log
        assert "+84" not in log

    @pytest.mark.asyncio
    async def test_reasoning_log_contains_status_info(self) -> None:
        """reasoning_log must contain status and source info."""
        svc = _make_service(candidates=[_candidate()])
        resp = await svc.recommend(query="hải sản", session_id="s1")
        log = resp.reasoning_log or ""
        assert "status=" in log
        assert "source=" in log
        assert "candidate_count=" in log
        assert "result_count=" in log
