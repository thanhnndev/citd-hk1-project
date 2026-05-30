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
    _grounded_results,
    _reranked_results,
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
    assert response.message == "I found 1 Ham Ninh place option(s) from Goong Places."

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
