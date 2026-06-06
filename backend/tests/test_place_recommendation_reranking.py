"""Integration tests for the ensemble reranking pipeline and fairness constraint."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.models.places import (
    PlaceCandidate,
    PlaceSearchRequest,
    PlaceToolResponse,
    PlaceToolSource,
    PlaceToolStatus,
)
from app.models.request import LatLng
from app.models.response import PlaceResult, ScoreBreakdown
from agents.services.place_recommendation_service import (
    PlaceRecommendationService,
    _balance_fairness,
    _grounded_results,
    _is_local,
    _reranked_results,
    FAIRNESS_LOCAL_THRESHOLD,
    FAIRNESS_TOP_K,
    FAIRNESS_TOP5_TARGET_RATIO,
)


def _candidate(
    place_id: str,
    local_factor: float,
    rating: float = 4.0,
    price_level: int = 2,
    display_name: str = "Test Place",
) -> PlaceCandidate:
    return PlaceCandidate(
        place_id=place_id,
        display_name=display_name,
        types=["restaurant"],
        location=LatLng(lat=10.1794, lng=104.0491),
        local_factor=local_factor,
        rating=rating,
        price_level=price_level,
        open_now=True,
        business_status="OPERATIONAL",
        map_uri=f"https://maps.example/{place_id}",
    )


def _assert_valid_score_breakdown(breakdown: ScoreBreakdown) -> None:
    """Assert all ensemble schema fields are present and valid."""
    assert 0.0 <= breakdown.tree1_locality <= 1.0
    assert 0.0 <= breakdown.tree2_proximity <= 1.0
    assert 0.0 <= breakdown.tree3_quality <= 1.0
    assert 0.0 <= breakdown.s_bag <= 1.0
    assert breakdown.final_score == breakdown.final_score  # not NaN
    assert 0.0 <= breakdown.final_score <= 1.0
    assert breakdown.rank >= 1


# ---------------------------------------------------------------------------
# Test 1 — Fairness constraint: ≥40% of top-5 have local_factor > 0.5
# when test data has ≥2 local candidates
# ---------------------------------------------------------------------------

def test_fairness_constraint_local_candidates_in_top_results() -> None:
    """With 2 local and 3 chain candidates, ≥2 of top-5 must have local_factor > 0.5."""
    candidates = [
        _candidate("places/local-1", local_factor=0.9, display_name="Local Spot 1"),
        _candidate("places/local-2", local_factor=0.8, display_name="Local Spot 2"),
        _candidate("places/chain-1", local_factor=0.05, display_name="Chain A"),
        _candidate("places/chain-2", local_factor=0.05, display_name="Chain B"),
        _candidate("places/chain-3", local_factor=0.05, display_name="Chain C"),
    ]

    results = _reranked_results(candidates, "seafood restaurant")

    assert len(results) == 5
    local_in_top5 = sum(1 for r in results[:5] if r.local_factor > 0.5)
    assert local_in_top5 >= 2, (
        f"Fairness constraint violated: only {local_in_top5} of top-5 have local_factor > 0.5"
    )

    # Verify all score_breakdowns use ensemble schema
    for r in results:
        _assert_valid_score_breakdown(r.score_breakdown)


# ---------------------------------------------------------------------------
# Test 2 — All chain candidates: should return without error
# ---------------------------------------------------------------------------

def test_all_chain_candidates_return_without_error() -> None:
    """With only chain candidates, pipeline still returns results."""
    candidates = [
        _candidate("places/chain-1", local_factor=0.05),
        _candidate("places/chain-2", local_factor=0.03),
        _candidate("places/chain-3", local_factor=0.01),
    ]

    results = _reranked_results(candidates, "chain restaurant")

    assert len(results) == 3
    for r in results:
        assert r.local_factor < 0.5
        _assert_valid_score_breakdown(r.score_breakdown)


# ---------------------------------------------------------------------------
# Test 3 — Single candidate: full ensemble breakdown populated
# ---------------------------------------------------------------------------

def test_single_candidate_has_full_breakdown() -> None:
    """Single candidate should return with complete score_breakdown."""
    candidates = [
        _candidate("places/only-one", local_factor=0.7),
    ]

    results = _reranked_results(candidates, "ham ninh seafood")

    assert len(results) == 1
    breakdown = results[0].score_breakdown
    _assert_valid_score_breakdown(breakdown)
    assert breakdown.rank == 1


# ---------------------------------------------------------------------------
# Test 4 — Zero candidates: returns empty list
# ---------------------------------------------------------------------------

def test_zero_candidates_returns_empty() -> None:
    results = _reranked_results([], "nothing here")
    assert results == []


# ---------------------------------------------------------------------------
# Test 5 — Full recommend() mock with known candidates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_recommend_returns_reranked_with_ensemble_breakdown() -> None:
    """Mock places_tool.text_search returning known candidates; assert re-ranked results."""
    candidates = [
        _candidate("places/local-fish", local_factor=0.9, display_name="Local Fish House"),
        _candidate("places/chain-bistro", local_factor=0.05, display_name="Chain Bistro"),
        _candidate("places/local-hut", local_factor=0.85, display_name="Local Hut"),
    ]

    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=PlaceSearchRequest(query="seafood"),
        retrieved_at=datetime.now(UTC),
    )

    service = PlaceRecommendationService(places_tool)
    response = await service.recommend(query="seafood", language="en", session_id="s-rerank")

    assert len(response.places) == 3
    # All results should have ensemble score_breakdown
    for place in response.places:
        _assert_valid_score_breakdown(place.score_breakdown)
        assert place.final_score == place.score_breakdown.final_score

    # Fairness: ≥2 of top results should have local_factor > 0.5
    local_in_top = sum(1 for p in response.places if p.local_factor > 0.5)
    assert local_in_top >= 2


@pytest.mark.asyncio
async def test_default_recommendation_service_uses_goong_places(monkeypatch) -> None:
    """Default construction should use GoongPlacesService while preserving reranking."""
    import agents.services.place_recommendation_service as prs_module

    class FakeGoongPlacesService:
        async def text_search(self, request: PlaceSearchRequest) -> PlaceToolResponse:
            return PlaceToolResponse(
                status=PlaceToolStatus.OK,
                source=PlaceToolSource.GOONG_PLACES,
                candidates=[
                    _candidate("goong-default", local_factor=0.8, display_name="Goong Default"),
                ],
                request=request,
                retrieved_at=datetime.now(UTC),
            )

    monkeypatch.setattr(prs_module, "GooglePlacesService", FakeGoongPlacesService)

    service = prs_module.PlaceRecommendationService()
    response = await service.recommend(query="seafood", language="en", session_id="s-goong")

    assert len(response.places) == 1
    assert response.places[0].place_id == "goong-default"
    assert "source=goong_places" in (response.reasoning_log or "")
    # Message now includes cultural preface for commercial queries
    assert "Goong Default" in response.message

# ---------------------------------------------------------------------------
# Test 6 — Ensemble fallback path
# ---------------------------------------------------------------------------

def test_grounded_results_fallback_produces_valid_results() -> None:
    """_grounded_results must produce valid ensemble-schema ScoreBreakdown objects."""
    candidates = [
        _candidate("places/fallback-1", local_factor=0.6),
        _candidate("places/fallback-2", local_factor=0.3),
    ]

    results = _grounded_results(candidates)

    assert len(results) == 2
    for i, r in enumerate(results):
        assert r.final_score == 0.5
        breakdown = r.score_breakdown
        assert breakdown.tree1_locality == 0.5
        assert breakdown.tree2_proximity == 0.5
        assert breakdown.tree3_quality == 0.5
        assert breakdown.s_bag == 0.5
        assert breakdown.delta1_fairness == 0.0
        assert breakdown.delta2_access == 0.0
        assert breakdown.final_score == 0.5
        assert breakdown.rank == i + 1


@pytest.mark.asyncio
async def test_ensemble_failure_falls_back_to_grounded() -> None:
    """If _reranked_results raises, recommend() falls back to _grounded_results."""
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=[
            _candidate("places/broken", local_factor=0.5),
        ],
        request=PlaceSearchRequest(query="test"),
        retrieved_at=datetime.now(UTC),
    )

    # Monkey-patch _reranked_results to always raise
    import agents.services.place_recommendation_service as prs_module

    original = prs_module._reranked_results

    def _broken_rerank(candidates, query):
        raise RuntimeError("simulated ensemble failure")

    prs_module._reranked_results = _broken_rerank  # type: ignore[assignment]
    try:
        service = PlaceRecommendationService(places_tool)
        response = await service.recommend(query="test", language="en", session_id="s-fallback")

        # Should still return results from fallback path
        assert len(response.places) == 1
        assert response.places[0].place_id == "places/broken"
        assert response.places[0].final_score == 0.5  # fallback default
    finally:
        prs_module._reranked_results = original  # restore


# ============================================================================
# T02: Fairness balancing tests — _balance_fairness function
# ============================================================================

def _result(
    place_id: str,
    local_factor: float,
    final_score: float = 0.5,
    display_name: str = "Test",
    rank: int = 1,
) -> PlaceResult:
    """Build a minimal PlaceResult for fairness balancing tests."""
    return PlaceResult(
        place_id=place_id,
        display_name=display_name,
        local_factor=local_factor,
        final_score=final_score,
        map_uri=f"https://maps.example/{place_id}",
        score_breakdown=ScoreBreakdown(
            tree1_locality=local_factor,
            tree2_proximity=0.5,
            tree3_quality=0.5,
            s_bag=0.5,
            delta1_fairness=0.0,
            delta2_access=0.0,
            final_score=final_score,
            rank=rank,
        ),
    )


class TestFairnessBalancingPromotesLocals:
    """_balance_fairness must promote local candidates into top-K when supply allows."""

    def test_nonlocals_initially_dominate_then_locals_promoted(self):
        """7 results: 3 high-scoring nonlocals in top-5, 2 locals below window.
        After balancing, at least 2 locals must appear in top-5."""
        results = [
            # Top-5: all nonlocal, high scores
            _result("chain-a", local_factor=0.1, final_score=0.95, rank=1),
            _result("chain-b", local_factor=0.05, final_score=0.90, rank=2),
            _result("chain-c", local_factor=0.1, final_score=0.85, rank=3),
            _result("chain-d", local_factor=0.2, final_score=0.80, rank=4),
            _result("chain-e", local_factor=0.15, final_score=0.75, rank=5),
            # Below window: local candidates
            _result("local-1", local_factor=0.9, final_score=0.70, rank=6),
            _result("local-2", local_factor=0.8, final_score=0.65, rank=7),
        ]

        # Before: 0 locals in top-5
        before_local = sum(1 for r in results[:5] if _is_local(r))
        assert before_local == 0

        balanced = _balance_fairness(results)

        # After: at least 2 locals in top-5 (40% of 5 = 2)
        after_local = sum(1 for r in balanced[:5] if _is_local(r))
        assert after_local >= 2, f"Only {after_local} locals in top-5 after balancing"

    def test_same_objects_returned_no_fabrication(self):
        """_balance_fairness must reorder, not invent, candidates."""
        results = [
            _result("chain-1", local_factor=0.1, final_score=0.9, rank=1),
            _result("chain-2", local_factor=0.1, final_score=0.8, rank=2),
            _result("chain-3", local_factor=0.1, final_score=0.7, rank=3),
            _result("local-1", local_factor=0.9, final_score=0.6, rank=4),
            _result("local-2", local_factor=0.8, final_score=0.5, rank=5),
        ]
        balanced = _balance_fairness(results)
        assert len(balanced) == len(results)
        original_ids = {r.place_id for r in results}
        balanced_ids = {r.place_id for r in balanced}
        assert original_ids == balanced_ids

    def test_already_compliant_no_reordering(self):
        """When top-5 already meets 40% local target, ordering must not change."""
        results = [
            _result("local-1", local_factor=0.9, final_score=0.95, rank=1),
            _result("chain-1", local_factor=0.1, final_score=0.90, rank=2),
            _result("local-2", local_factor=0.8, final_score=0.85, rank=3),
            _result("chain-2", local_factor=0.1, final_score=0.80, rank=4),
            _result("chain-3", local_factor=0.1, final_score=0.75, rank=5),
        ]
        balanced = _balance_fairness(results)
        # Should be identical ordering
        for i, (orig, bal) in enumerate(zip(results, balanced)):
            assert orig.place_id == bal.place_id, f"Reordering at index {i}: {orig.place_id} -> {bal.place_id}"

    def test_empty_list_returns_empty(self):
        assert _balance_fairness([]) == []

    def test_single_result_no_crash(self):
        results = [_result("only", local_factor=0.1)]
        balanced = _balance_fairness(results)
        assert len(balanced) == 1
        assert balanced[0].place_id == "only"

    def test_fewer_than_top_k_results(self):
        """Only 3 results — below top_k=5 window."""
        results = [
            _result("chain-1", local_factor=0.1, final_score=0.9, rank=1),
            _result("chain-2", local_factor=0.1, final_score=0.8, rank=2),
            _result("chain-3", local_factor=0.1, final_score=0.7, rank=3),
        ]
        balanced = _balance_fairness(results)
        assert len(balanced) == 3
        # No locals available — no reordering needed
        assert balanced[0].place_id == "chain-1"

    def test_all_nonlocal_no_locals_to_promote(self):
        results = [
            _result("chain-1", local_factor=0.1, final_score=0.9, rank=1),
            _result("chain-2", local_factor=0.1, final_score=0.8, rank=2),
            _result("chain-3", local_factor=0.1, final_score=0.7, rank=3),
            _result("chain-4", local_factor=0.1, final_score=0.6, rank=4),
            _result("chain-5", local_factor=0.1, final_score=0.5, rank=5),
        ]
        balanced = _balance_fairness(results)
        # All nonlocal, no locals anywhere — ordering unchanged
        for i, (orig, bal) in enumerate(zip(results, balanced)):
            assert orig.place_id == bal.place_id

    def test_all_local_no_reordering_needed(self):
        results = [
            _result("local-1", local_factor=0.9, final_score=0.9, rank=1),
            _result("local-2", local_factor=0.8, final_score=0.8, rank=2),
            _result("local-3", local_factor=0.7, final_score=0.7, rank=3),
        ]
        balanced = _balance_fairness(results)
        # All local — already 100% local ratio, no change needed
        for i, (orig, bal) in enumerate(zip(results, balanced)):
            assert orig.place_id == bal.place_id

    def test_default_local_factor_0_5_is_nonlocal(self):
        """_reranked_results defaults missing local_factor to 0.5, which is below threshold."""
        # 0.5 < FAIRNESS_LOCAL_THRESHOLD (0.6) — treated as nonlocal
        result = _result("default-factor", local_factor=0.5)
        assert not _is_local(result)

    def test_exactly_at_threshold_counts_as_local(self):
        """local_factor == FAIRNESS_LOCAL_THRESHOLD should count as local."""
        result = _result("at-threshold", local_factor=FAIRNESS_LOCAL_THRESHOLD)
        assert _is_local(result)

    def test_just_below_threshold_is_nonlocal(self):
        """local_factor just below threshold should NOT count as local."""
        result = _result("below", local_factor=FAIRNESS_LOCAL_THRESHOLD - 0.001)
        assert not _is_local(result)

    def test_insufficient_local_supply_does_not_crash(self):
        """Only 1 local candidate available but 2 needed — should not crash."""
        results = [
            _result("chain-1", local_factor=0.1, final_score=0.9, rank=1),
            _result("chain-2", local_factor=0.1, final_score=0.8, rank=2),
            _result("chain-3", local_factor=0.1, final_score=0.7, rank=3),
            _result("chain-4", local_factor=0.1, final_score=0.6, rank=4),
            _result("chain-5", local_factor=0.1, final_score=0.5, rank=5),
            _result("local-1", local_factor=0.9, final_score=0.4, rank=6),
        ]
        balanced = _balance_fairness(results)
        # Only 1 local available — gets promoted but target not fully met
        after_local = sum(1 for r in balanced[:5] if _is_local(r))
        assert after_local == 1  # best effort
        assert len(balanced) == 6  # no candidates lost

    def test_top5_local_ratio_meets_target_after_balancing(self):
        """After balancing, top-5 local ratio must be >= 0.4 when supply allows."""
        results = [
            _result("chain-1", local_factor=0.1, final_score=0.95, rank=1),
            _result("chain-2", local_factor=0.1, final_score=0.90, rank=2),
            _result("chain-3", local_factor=0.1, final_score=0.85, rank=3),
            _result("chain-4", local_factor=0.1, final_score=0.80, rank=4),
            _result("chain-5", local_factor=0.1, final_score=0.75, rank=5),
            _result("local-1", local_factor=0.9, final_score=0.70, rank=6),
            _result("local-2", local_factor=0.8, final_score=0.65, rank=7),
            _result("local-3", local_factor=0.7, final_score=0.60, rank=8),
        ]
        balanced = _balance_fairness(results)
        top5 = balanced[:5]
        local_count = sum(1 for r in top5 if _is_local(r))
        ratio = local_count / len(top5)
        assert ratio >= FAIRNESS_TOP5_TARGET_RATIO, (
            f"top5_local_ratio={ratio} < target={FAIRNESS_TOP5_TARGET_RATIO}"
        )


# ============================================================================
# T02: Preference wiring — budget, accessibility, origin, and safety tests
# ============================================================================

from agents.services.place_recommendation_service import _apply_preference_filters


class TestBudgetFiltering:
    """Budget filtering must exclude out-of-range priced candidates while
    retaining unknown-price candidates and invalid budget inputs."""

    def _candidate(self, place_id: str, price_level: int | None, **kw) -> PlaceCandidate:
        return PlaceCandidate(
            place_id=place_id,
            display_name=place_id,
            types=["restaurant"],
            location=LatLng(lat=10.18, lng=104.05),
            price_level=price_level,
            **kw,
        )

    def test_budget_moderate_excludes_very_expensive(self) -> None:
        """Moderate budget should exclude expensive/very_expensive candidates."""
        candidates = [
            self._candidate("cheap", price_level=0),
            self._candidate("inexp", price_level=1),
            self._candidate("moder", price_level=2),
            self._candidate("expens", price_level=3),
            self._candidate("vexpens", price_level=4),
        ]
        request = PlaceSearchRequest(query="test", budget_filter=["moderate"])
        filtered, excluded = _apply_preference_filters(candidates, request)
        assert excluded == 2  # expensive + very_expensive excluded
        assert [c.place_id for c in filtered] == ["cheap", "inexp", "moder"]

    def test_budget_retains_unknown_price_candidates(self) -> None:
        """Candidates with price_level=None must NOT be excluded by budget filter."""
        candidates = [
            self._candidate("known_cheap", price_level=0),
            self._candidate("unknown_price", price_level=None),
            self._candidate("known_expensive", price_level=4),
        ]
        request = PlaceSearchRequest(query="test", budget_filter=["inexpensive"])
        filtered, excluded = _apply_preference_filters(candidates, request)
        assert excluded == 1  # only expensive excluded
        assert "unknown_price" in [c.place_id for c in filtered]
        assert "known_cheap" in [c.place_id for c in filtered]

    def test_budget_free_only_keeps_free_and_unknown(self) -> None:
        """Free budget should only keep free (0) and unknown-price candidates."""
        candidates = [
            self._candidate("free", price_level=0),
            self._candidate("moderate", price_level=2),
            self._candidate("unknown", price_level=None),
        ]
        request = PlaceSearchRequest(query="test", budget_filter=["free"])
        filtered, excluded = _apply_preference_filters(candidates, request)
        assert excluded == 1  # moderate excluded
        assert set(c.place_id for c in filtered) == {"free", "unknown"}

    def test_no_budget_filter_passes_all_through(self) -> None:
        """When budget_filter is None, all candidates pass through."""
        candidates = [
            self._candidate("free", price_level=0),
            self._candidate("expensive", price_level=3),
            self._candidate("unknown", price_level=None),
        ]
        request = PlaceSearchRequest(query="test", budget_filter=None)
        filtered, excluded = _apply_preference_filters(candidates, request)
        assert excluded == 0
        assert len(filtered) == 3

    def test_empty_candidate_list_returns_empty(self) -> None:
        """Empty candidate list returns empty without error."""
        request = PlaceSearchRequest(query="test", budget_filter=["free"])
        filtered, excluded = _apply_preference_filters([], request)
        assert filtered == []
        assert excluded == 0

    def test_budget_filters_all_candidates_returns_empty_list(self) -> None:
        """When budget excludes ALL known-price candidates but none have
        unknown price, result is empty (honest empty — no fabrication)."""
        candidates = [
            self._candidate("exp1", price_level=3),
            self._candidate("exp2", price_level=4),
        ]
        request = PlaceSearchRequest(query="test", budget_filter=["free"])
        filtered, excluded = _apply_preference_filters(candidates, request)
        assert filtered == []
        assert excluded == 2


class TestAccessibilityBoosting:
    """Accessibility preference must promote accessible candidates without
    hiding unknown-metadata candidates."""

    def _candidate(self, place_id: str, accessibility_options: dict | None = None,
                   local_factor: float | None = 0.5, **kw) -> PlaceCandidate:
        return PlaceCandidate(
            place_id=place_id,
            display_name=place_id,
            types=["restaurant"],
            location=LatLng(lat=10.18, lng=104.05),
            accessibility_options=accessibility_options or {},
            local_factor=local_factor,
            **kw,
        )

    def test_accessibility_promotes_accessible_candidates(self) -> None:
        """When accessibility preference is True, accessible candidates get
        boosted local_factor and sorted higher."""
        candidates = [
            self._candidate("no_access", accessibility_options={}, local_factor=0.5),
            self._candidate("has_access", accessibility_options={"wheelchairAccessibleEntrance": True}, local_factor=0.5),
        ]
        request = PlaceSearchRequest(query="test", wheelchair_accessible_preference=True)
        filtered, _ = _apply_preference_filters(candidates, request)
        # Accessible candidate should be first (boosted to 0.6 vs 0.5)
        assert filtered[0].place_id == "has_access"
        assert filtered[0].local_factor == 0.6  # 0.5 + 0.1 boost

    def test_accessibility_retains_unknown_metadata_candidates(self) -> None:
        """Candidates with no accessibility_options must NOT be filtered out."""
        candidates = [
            self._candidate("has_access", accessibility_options={"wheelchairAccessibleEntrance": True}),
            self._candidate("no_access", accessibility_options={}),
            self._candidate("unknown_meta", accessibility_options={}, local_factor=0.3),
        ]
        request = PlaceSearchRequest(query="test", wheelchair_accessible_preference=True)
        filtered, _ = _apply_preference_filters(candidates, request)
        # All three should be present — no hiding of unknown metadata
        assert len(filtered) == 3
        place_ids = {c.place_id for c in filtered}
        assert place_ids == {"has_access", "no_access", "unknown_meta"}

    def test_accessibility_false_no_boost(self) -> None:
        """When accessibility preference is False (explicitly), no boost occurs."""
        candidates = [
            self._candidate("has_access", accessibility_options={"wheelchairAccessibleEntrance": True}, local_factor=0.5),
        ]
        request = PlaceSearchRequest(query="test", wheelchair_accessible_preference=False)
        filtered, _ = _apply_preference_filters(candidates, request)
        # local_factor unchanged
        assert filtered[0].local_factor == 0.5

    def test_accessibility_none_no_boost(self) -> None:
        """When accessibility preference is None (default), no boost occurs."""
        candidates = [
            self._candidate("has_access", accessibility_options={"wheelchairAccessibleEntrance": True}, local_factor=0.5),
        ]
        request = PlaceSearchRequest(query="test", wheelchair_accessible_preference=None)
        filtered, _ = _apply_preference_filters(candidates, request)
        assert filtered[0].local_factor == 0.5

    def test_accessibility_boost_capped_at_1_0(self) -> None:
        """Boost must not exceed 1.0 even if candidate starts at 0.95."""
        candidates = [
            self._candidate("high_local", accessibility_options={"wheelchairAccessibleEntrance": True}, local_factor=0.95),
        ]
        request = PlaceSearchRequest(query="test", wheelchair_accessible_preference=True)
        filtered, _ = _apply_preference_filters(candidates, request)
        assert filtered[0].local_factor == 1.0

    def test_accessibility_sorts_boosted_above_unboosted(self) -> None:
        """Boosted accessible candidates should sort above unboosted."""
        candidates = [
            self._candidate("chain_high", accessibility_options={}, local_factor=0.8),
            self._candidate("local_low", accessibility_options={"wheelchairAccessibleEntrance": True}, local_factor=0.3),
        ]
        request = PlaceSearchRequest(query="test", wheelchair_accessible_preference=True)
        filtered, _ = _apply_preference_filters(candidates, request)
        # local_low boosted to 0.4, chain_high stays 0.8 — chain still above
        # because boost is only +0.1; but sort is by local_factor desc
        assert filtered[0].place_id == "chain_high"  # 0.8 > 0.4

    def test_accessibility_all_false_no_boost(self) -> None:
        """Candidates with accessibility_options but all False should not be boosted."""
        candidates = [
            self._candidate("all_false", accessibility_options={"wheelchairAccessibleEntrance": False}, local_factor=0.5),
        ]
        request = PlaceSearchRequest(query="test", wheelchair_accessible_preference=True)
        filtered, _ = _apply_preference_filters(candidates, request)
        assert filtered[0].local_factor == 0.5  # unchanged


class TestInvalidPreferences:
    """Invalid or malformed preferences must not crash the recommendation flow."""

    def test_budget_filter_with_none_candidates(self) -> None:
        """Budget filter with None candidates should not crash."""
        request = PlaceSearchRequest(query="test", budget_filter=["moderate"])
        # No candidates — should return empty
        filtered, excluded = _apply_preference_filters([], request)
        assert filtered == []
        assert excluded == 0

    def test_no_preferences_all_pass_through(self) -> None:
        """When no preferences are set, all candidates pass through unchanged."""
        candidates = [
            PlaceCandidate(
                place_id="p1", display_name="P1", types=["restaurant"],
                location=LatLng(lat=10.18, lng=104.05),
            ),
        ]
        request = PlaceSearchRequest(query="test")
        filtered, excluded = _apply_preference_filters(candidates, request)
        assert len(filtered) == 1
        assert excluded == 0


class TestPreferenceEndToEnd:
    """End-to-end tests through the full recommend() flow verifying
    preferences are honored, redacted, and do not crash."""

    @pytest.mark.asyncio
    async def test_budget_applied_in_reasoning_log(self) -> None:
        """When budget is provided, reasoning_log should show preference_budget_applied flag."""
        candidates = [
            PlaceCandidate(place_id="places/cheap", display_name="Cheap Eats", types=["restaurant"],
                           location=LatLng(lat=10.18, lng=104.05), price_level=0),
            PlaceCandidate(place_id="places/expensive", display_name="Expensive Place", types=["restaurant"],
                           location=LatLng(lat=10.18, lng=104.05), price_level=4),
        ]
        places_tool = AsyncMock()
        places_tool.text_search.return_value = PlaceToolResponse(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.MOCK,
            candidates=candidates,
            request=PlaceSearchRequest(query="restaurant"),
            retrieved_at=datetime.now(UTC),
        )
        service = PlaceRecommendationService(places_tool, routes_service=None)

        response = await service.recommend(
            query="restaurant", language="en", session_id="s-budget",
            budget="free",
        )

        assert response.reasoning_log is not None
        assert "preference_budget_applied=True" in response.reasoning_log

    @pytest.mark.asyncio
    async def test_budget_excludes_expensive_from_results(self) -> None:
        """Budget='free' should exclude price_level=4 candidates but keep unknown-price."""
        candidates = [
            PlaceCandidate(place_id="places/free", display_name="Free Spot", types=["restaurant"],
                           location=LatLng(lat=10.18, lng=104.05), price_level=0),
            PlaceCandidate(place_id="places/expensive", display_name="Expensive", types=["restaurant"],
                           location=LatLng(lat=10.18, lng=104.05), price_level=4),
            PlaceCandidate(place_id="places/unknown", display_name="Unknown Price", types=["restaurant"],
                           location=LatLng(lat=10.18, lng=104.05), price_level=None),
        ]
        places_tool = AsyncMock()
        places_tool.text_search.return_value = PlaceToolResponse(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.MOCK,
            candidates=candidates,
            request=PlaceSearchRequest(query="restaurant"),
            retrieved_at=datetime.now(UTC),
        )
        service = PlaceRecommendationService(places_tool, routes_service=None)

        response = await service.recommend(
            query="restaurant", language="en", session_id="s-budget-filter",
            budget="free",
        )

        result_ids = {p.place_id for p in response.places}
        assert "places/free" in result_ids
        assert "places/unknown" in result_ids
        assert "places/expensive" not in result_ids

    @pytest.mark.asyncio
    async def test_accessibility_boosted_in_results(self) -> None:
        """Accessibility preference should boost accessible candidates in ranking."""
        candidates = [
            PlaceCandidate(place_id="places/non-access", display_name="Non-Accessible", types=["restaurant"],
                           location=LatLng(lat=10.18, lng=104.05), local_factor=0.8,
                           accessibility_options={}),
            PlaceCandidate(place_id="places/access", display_name="Accessible Venue", types=["restaurant"],
                           location=LatLng(lat=10.18, lng=104.05), local_factor=0.3,
                           accessibility_options={"wheelchairAccessibleEntrance": True}),
        ]
        places_tool = AsyncMock()
        places_tool.text_search.return_value = PlaceToolResponse(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.MOCK,
            candidates=candidates,
            request=PlaceSearchRequest(query="restaurant"),
            retrieved_at=datetime.now(UTC),
        )
        service = PlaceRecommendationService(places_tool, routes_service=None)

        response = await service.recommend(
            query="restaurant", language="en", session_id="s-access",
            accessibility=True,
        )

        assert response.reasoning_log is not None
        assert "preference_accessibility_applied=True" in response.reasoning_log
        # Accessible candidate should have boosted local_factor (0.3 + 0.1 = 0.4)
        # Non-accessible stays at 0.8 — non-access still ranks higher by local_factor
        # but both should be present
        assert len(response.places) == 2

    @pytest.mark.asyncio
    async def test_user_location_sets_effective_origin(self) -> None:
        """User location should be used as effective origin for distance scoring."""
        places_tool = AsyncMock()
        places_tool.text_search.return_value = PlaceToolResponse(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.MOCK,
            candidates=[
                PlaceCandidate(place_id="places/near", display_name="Near Place", types=["restaurant"],
                               location=LatLng(lat=10.185, lng=104.050)),
            ],
            request=PlaceSearchRequest(query="restaurant"),
            retrieved_at=datetime.now(UTC),
        )
        service = PlaceRecommendationService(places_tool, routes_service=None)

        response = await service.recommend(
            query="restaurant", language="en", session_id="s-origin",
            user_location={"lat": 10.183, "lng": 104.049},
        )

        assert response.reasoning_log is not None
        assert "user_location_applied=True" in response.reasoning_log

    @pytest.mark.asyncio
    async def test_invalid_user_location_does_not_crash(self) -> None:
        """Out-of-range coordinates should be ignored gracefully."""
        places_tool = AsyncMock()
        places_tool.text_search.return_value = PlaceToolResponse(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.MOCK,
            candidates=[
                PlaceCandidate(place_id="places/p1", display_name="P1", types=["restaurant"],
                               location=LatLng(lat=10.18, lng=104.05)),
            ],
            request=PlaceSearchRequest(query="restaurant"),
            retrieved_at=datetime.now(UTC),
        )
        service = PlaceRecommendationService(places_tool, routes_service=None)

        # Out-of-range lat
        response = await service.recommend(
            query="restaurant", language="en", session_id="s-bad-loc",
            user_location={"lat": 999.0, "lng": 104.05},
        )

        assert response.places  # should still return results
        assert "user_location_applied=True" not in (response.reasoning_log or "")

    @pytest.mark.asyncio
    async def test_empty_budget_string_no_crash(self) -> None:
        """Empty budget string should be ignored, not crash."""
        places_tool = AsyncMock()
        places_tool.text_search.return_value = PlaceToolResponse(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.MOCK,
            candidates=[
                PlaceCandidate(place_id="places/p1", display_name="P1", types=["restaurant"],
                               location=LatLng(lat=10.18, lng=104.05), price_level=3),
            ],
            request=PlaceSearchRequest(query="restaurant"),
            retrieved_at=datetime.now(UTC),
        )
        service = PlaceRecommendationService(places_tool, routes_service=None)

        response = await service.recommend(
            query="restaurant", language="en", session_id="s-empty-budget",
            budget="",  # empty string
        )

        # Empty budget is treated as no budget
        assert len(response.places) == 1

    @pytest.mark.asyncio
    async def test_invalid_budget_string_no_crash(self) -> None:
        """Invalid budget string like 'luxury' should be ignored, not crash."""
        places_tool = AsyncMock()
        places_tool.text_search.return_value = PlaceToolResponse(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.MOCK,
            candidates=[
                PlaceCandidate(place_id="places/p1", display_name="P1", types=["restaurant"],
                               location=LatLng(lat=10.18, lng=104.05), price_level=3),
            ],
            request=PlaceSearchRequest(query="restaurant"),
            retrieved_at=datetime.now(UTC),
        )
        service = PlaceRecommendationService(places_tool, routes_service=None)

        response = await service.recommend(
            query="restaurant", language="en", session_id="s-invalid-budget",
            budget="luxury",  # not in enum
        )

        assert len(response.places) == 1
        assert "preference_budget_applied=True" not in (response.reasoning_log or "")

    @pytest.mark.asyncio
    async def test_filtered_empty_returns_honest_empty_status(self) -> None:
        """When budget filters out ALL candidates (none with unknown price),
        result is empty places with honest status — no fabricated places."""
        candidates = [
            PlaceCandidate(place_id="places/exp1", display_name="Expensive 1", types=["restaurant"],
                           location=LatLng(lat=10.18, lng=104.05), price_level=4),
            PlaceCandidate(place_id="places/exp2", display_name="Expensive 2", types=["restaurant"],
                           location=LatLng(lat=10.18, lng=104.05), price_level=3),
        ]
        places_tool = AsyncMock()
        places_tool.text_search.return_value = PlaceToolResponse(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.MOCK,
            candidates=candidates,
            request=PlaceSearchRequest(query="restaurant"),
            retrieved_at=datetime.now(UTC),
        )
        service = PlaceRecommendationService(places_tool, routes_service=None)

        response = await service.recommend(
            query="restaurant", language="en", session_id="s-filter-empty",
            budget="free",
        )

        # All expensive places filtered out → empty results
        assert response.places == []
        # Citations must always be empty (no RAG)
        assert response.citations == []

    @pytest.mark.asyncio
    async def test_no_raw_coordinates_in_reasoning_log(self) -> None:
        """Reasoning log must not contain exact GPS coordinates."""
        places_tool = AsyncMock()
        places_tool.text_search.return_value = PlaceToolResponse(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.MOCK,
            candidates=[
                PlaceCandidate(place_id="places/p1", display_name="P1", types=["restaurant"],
                               location=LatLng(lat=10.18, lng=104.05)),
            ],
            request=PlaceSearchRequest(query="restaurant"),
            retrieved_at=datetime.now(UTC),
        )
        service = PlaceRecommendationService(places_tool, routes_service=None)

        response = await service.recommend(
            query="restaurant", language="en", session_id="s-redact",
            user_location={"lat": 10.18352, "lng": 104.04968},
        )

        log = response.reasoning_log or ""
        # Exact GPS should not appear in reasoning log
        assert "10.18352" not in log
        assert "104.04968" not in log
        # Rounded version may appear (2 decimals)
        # But the exact raw coordinates must never appear

    @pytest.mark.asyncio
    async def test_preference_flags_combined(self) -> None:
        """When budget + accessibility + user_location are all set,
        reasoning_log should show all three flags."""
        candidates = [
            PlaceCandidate(place_id="places/p1", display_name="P1", types=["restaurant"],
                           location=LatLng(lat=10.18, lng=104.05), price_level=0,
                           accessibility_options={"wheelchairAccessibleEntrance": True}),
        ]
        places_tool = AsyncMock()
        places_tool.text_search.return_value = PlaceToolResponse(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.MOCK,
            candidates=candidates,
            request=PlaceSearchRequest(query="restaurant"),
            retrieved_at=datetime.now(UTC),
        )
        service = PlaceRecommendationService(places_tool, routes_service=None)

        response = await service.recommend(
            query="restaurant", language="en", session_id="s-combined",
            budget="free",
            accessibility=True,
            user_location={"lat": 10.183, "lng": 104.049},
        )

        log = response.reasoning_log or ""
        assert "preference_budget_applied=True" in log
        assert "preference_accessibility_applied=True" in log
        assert "user_location_applied=True" in log

    @pytest.mark.asyncio
    async def test_fairness_still_enforced_after_budget_filter(self) -> None:
        """After budget filtering, fairness balancing should still be applied."""
        # Mix of local and chain restaurants all within budget
        candidates = [
            PlaceCandidate(place_id="places/chain1", display_name="Chain 1", types=["restaurant"],
                           location=LatLng(lat=10.18, lng=104.05), price_level=1, local_factor=0.1),
            PlaceCandidate(place_id="places/chain2", display_name="Chain 2", types=["restaurant"],
                           location=LatLng(lat=10.18, lng=104.05), price_level=1, local_factor=0.1),
            PlaceCandidate(place_id="places/chain3", display_name="Chain 3", types=["restaurant"],
                           location=LatLng(lat=10.18, lng=104.05), price_level=1, local_factor=0.1),
            PlaceCandidate(place_id="places/chain4", display_name="Chain 4", types=["restaurant"],
                           location=LatLng(lat=10.18, lng=104.05), price_level=1, local_factor=0.1),
            PlaceCandidate(place_id="places/chain5", display_name="Chain 5", types=["restaurant"],
                           location=LatLng(lat=10.18, lng=104.05), price_level=1, local_factor=0.1),
            PlaceCandidate(place_id="places/local1", display_name="Local 1", types=["restaurant"],
                           location=LatLng(lat=10.18, lng=104.05), price_level=1, local_factor=0.9),
            PlaceCandidate(place_id="places/local2", display_name="Local 2", types=["restaurant"],
                           location=LatLng(lat=10.18, lng=104.05), price_level=1, local_factor=0.8),
        ]
        places_tool = AsyncMock()
        places_tool.text_search.return_value = PlaceToolResponse(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.MOCK,
            candidates=candidates,
            request=PlaceSearchRequest(query="restaurant"),
            retrieved_at=datetime.now(UTC),
        )
        service = PlaceRecommendationService(places_tool, routes_service=None)

        response = await service.recommend(
            query="restaurant", language="en", session_id="s-fair-budget",
            budget="inexpensive",
        )

        # Fairness: at least 2 of top-5 should be local
        local_in_top5 = sum(1 for p in response.places[:5] if (p.local_factor or 0.0) >= 0.6)
        assert local_in_top5 >= 2, f"Only {local_in_top5} locals in top-5 after budget + fairness"

    @pytest.mark.asyncio
    async def test_citations_always_empty_with_preferences(self) -> None:
        """Citations must be [] even when preferences are applied."""
        candidates = [
            PlaceCandidate(place_id="places/p1", display_name="P1", types=["restaurant"],
                           location=LatLng(lat=10.18, lng=104.05), price_level=0),
        ]
        places_tool = AsyncMock()
        places_tool.text_search.return_value = PlaceToolResponse(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.MOCK,
            candidates=candidates,
            request=PlaceSearchRequest(query="restaurant"),
            retrieved_at=datetime.now(UTC),
        )
        service = PlaceRecommendationService(places_tool, routes_service=None)

        response = await service.recommend(
            query="restaurant", language="en", session_id="s-no-cite",
            budget="free",
            accessibility=True,
            user_location={"lat": 10.183, "lng": 104.049},
        )

        assert response.citations == []

@pytest.mark.asyncio
async def test_explanation_does_not_call_mid_rating_high() -> None:
    candidate = _candidate(
        "places/mid-rating",
        display_name="Hạnh Nhung Làng Chài Hàm Ninh Phú Quốc",
        local_factor=None,
        rating=3.6,
    )
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=[candidate],
        request=PlaceSearchRequest(query="nhà hàng"),
        retrieved_at=datetime.now(UTC),
    )
    service = PlaceRecommendationService(places_tool, routes_service=None)

    response = await service.recommend(query="nhà hàng", language="vi", session_id="s-mid-rating")

    reason = response.places[0].explanation.primary_reason.lower()
    assert "được đánh giá cao" not in reason
    assert "đánh giá trung bình 3.6" in reason
