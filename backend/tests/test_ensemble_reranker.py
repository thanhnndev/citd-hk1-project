"""Tests for EnsembleReranker: 3 decision trees + bagging + boosting pipeline.

Covers all tree branches, bagging average, boosting corrections, final score
clipping, sorting, rank assignment, and the full end-to-end pipeline.
"""

from __future__ import annotations

import pytest

from app.models.places import PlaceCandidate, RouteContext
from app.models.request import LatLng
from app.models.response import ScoreBreakdown
from app.services.ensemble_reranker import EnsembleReranker, LEARNING_RATE

LEARNING_RATE = 0.3


def make_candidate(**overrides: object) -> PlaceCandidate:
    """Factory — start with a rich default candidate, apply overrides."""
    base = PlaceCandidate(
        place_id="ChIJtest",
        display_name="Test Restaurant",
        location=LatLng(lat=10.1798, lng=104.0498),
        types=["seafood_restaurant", "restaurant"],
        primary_type="seafood_restaurant",
        rating=4.6,
        price_level=2,
        open_now=True,
        local_factor=0.8,
        route_context=RouteContext(distance_meters=500),
        accessibility_options={},
    )
    return base.model_copy(update=overrides)


reranker = EnsembleReranker()


# ---------------------------------------------------------------------------
# Tree 1: Locality-first decision tree
# ---------------------------------------------------------------------------


class TestTree1Locality:
    """Tree 1 rewards locally-owned businesses with an open-now bonus."""

    @pytest.mark.parametrize(
        "local_factor,is_open_now,expected",
        [
            pytest.param(0.8, 1, 0.9, id="high_local_factor_and_open"),
            pytest.param(0.8, 0, 0.7, id="high_local_factor_closed"),
            pytest.param(0.5, 1, 0.5, id="medium_local_factor"),
            pytest.param(0.2, 0, 0.2, id="low_local_factor"),
        ],
    )
    def test_locality_branches(
        self, local_factor: float, is_open_now: int, expected: float
    ) -> None:
        feat = {"local_factor": local_factor, "is_open_now": is_open_now}
        assert EnsembleReranker._tree1_locality(feat) == pytest.approx(expected)

    def test_boundary_local_factor_06(self) -> None:
        """Exactly 0.6 is NOT > 0.6, so falls to the 0.5 branch."""
        feat = {"local_factor": 0.6, "is_open_now": 1}
        assert EnsembleReranker._tree1_locality(feat) == pytest.approx(0.5)

    def test_boundary_local_factor_03(self) -> None:
        """Exactly 0.3 is NOT > 0.3, so falls to the 0.2 branch."""
        feat = {"local_factor": 0.3, "is_open_now": 0}
        assert EnsembleReranker._tree1_locality(feat) == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# Tree 2: Proximity-first decision tree
# ---------------------------------------------------------------------------


class TestTree2Proximity:
    """Tree 2 rewards closer venues, modulated by rating and local factor."""

    def test_very_close(self) -> None:
        feat = {"distance_meters": 100, "rating": 4.0, "local_factor": 0.5}
        assert EnsembleReranker._tree2_proximity(feat) == pytest.approx(0.9)

    def test_boundary_at_300(self) -> None:
        """Exactly 300 is NOT < 300, falls to 300-800 branch."""
        feat = {"distance_meters": 300, "rating": 4.5, "local_factor": 0.5}
        # 0.65 + (4.5 - 3.0) * 0.1 = 0.65 + 0.15 = 0.8
        assert EnsembleReranker._tree2_proximity(feat) == pytest.approx(0.8)

    @pytest.mark.parametrize(
        "distance,rating,expected",
        [
            pytest.param(400, 4.0, 0.65 + (4.0 - 3.0) * 0.1, id="400m_rating4"),
            pytest.param(799, 3.5, 0.65 + (3.5 - 3.0) * 0.1, id="799m_rating35"),
        ],
    )
    def test_mid_distance_formula(
        self, distance: int, rating: float, expected: float
    ) -> None:
        feat = {"distance_meters": distance, "rating": rating, "local_factor": 0.5}
        assert EnsembleReranker._tree2_proximity(feat) == pytest.approx(expected)

    def test_boundary_at_800(self) -> None:
        """Exactly 800 is NOT < 800, falls to 800-2000 branch."""
        feat = {"distance_meters": 800, "rating": 4.0, "local_factor": 0.7}
        # 0.4 + 0.7 * 0.2 = 0.54
        assert EnsembleReranker._tree2_proximity(feat) == pytest.approx(0.54)

    @pytest.mark.parametrize(
        "distance,local_factor,expected",
        [
            pytest.param(1000, 0.0, 0.4 + 0.0 * 0.2, id="1000m_no_local"),
            pytest.param(1999, 1.0, 0.4 + 1.0 * 0.2, id="1999m_full_local"),
        ],
    )
    def test_far_distance_formula(
        self, distance: int, local_factor: float, expected: float
    ) -> None:
        feat = {"distance_meters": distance, "rating": 3.0, "local_factor": local_factor}
        assert EnsembleReranker._tree2_proximity(feat) == pytest.approx(expected)

    def test_boundary_at_2000(self) -> None:
        """Exactly 2000 is NOT < 2000, falls to >= 2000 branch."""
        feat = {"distance_meters": 2000, "rating": 4.0, "local_factor": 0.9}
        assert EnsembleReranker._tree2_proximity(feat) == pytest.approx(0.15)

    def test_very_far(self) -> None:
        feat = {"distance_meters": 5000, "rating": 5.0, "local_factor": 1.0}
        assert EnsembleReranker._tree2_proximity(feat) == pytest.approx(0.15)


# ---------------------------------------------------------------------------
# Tree 3: Quality-first decision tree
# ---------------------------------------------------------------------------


class TestTree3Quality:
    """Tree 3 rewards high-rated, affordable venues with locality bonus."""

    @pytest.mark.parametrize(
        "rating,price_level,local_factor,expected",
        [
            pytest.param(4.5, 2, 0.0, 0.85 + 0.0 * 0.15, id="top_rating_mid_price"),
            pytest.param(4.8, 1, 0.8, 0.85 + 0.8 * 0.15, id="top_rating_low_price"),
            pytest.param(5.0, 2, 1.0, 0.85 + 1.0 * 0.15, id="perfect_rating_max_local"),
        ],
    )
    def test_premium_branch(
        self, rating: float, price_level: int, local_factor: float, expected: float
    ) -> None:
        feat = {"rating": rating, "price_level": price_level, "local_factor": local_factor}
        assert EnsembleReranker._tree3_quality(feat) == pytest.approx(expected)

    def test_boundary_rating_45(self) -> None:
        """Exactly 4.5 IS >= 4.5, enters premium branch."""
        feat = {"rating": 4.5, "price_level": 2, "local_factor": 0.0}
        assert EnsembleReranker._tree3_quality(feat) == pytest.approx(0.85)

    def test_price_level_boundary_2(self) -> None:
        """price_level=2 IS <= 2, so premium branch fires if rating>=4.5."""
        feat = {"rating": 4.6, "price_level": 2, "local_factor": 0.0}
        assert EnsembleReranker._tree3_quality(feat) == pytest.approx(0.85)

    def test_good_rating_free_venue(self) -> None:
        """rating>=4.0 and price_level<=1."""
        feat = {"rating": 4.2, "price_level": 0, "local_factor": 0.5}
        assert EnsembleReranker._tree3_quality(feat) == pytest.approx(0.75)

    def test_good_rating_boundary_price_1(self) -> None:
        """rating>=4.0 and price_level=1."""
        feat = {"rating": 4.0, "price_level": 1, "local_factor": 0.5}
        assert EnsembleReranker._tree3_quality(feat) == pytest.approx(0.75)

    def test_rating_40_price_2_falls_through(self) -> None:
        """rating>=4.0 but price_level=2 (not <=1) → falls to rating>=3.5 branch."""
        feat = {"rating": 4.0, "price_level": 2, "local_factor": 0.5}
        # 0.5 + (2 - 2) * 0.05 = 0.5
        assert EnsembleReranker._tree3_quality(feat) == pytest.approx(0.5)

    @pytest.mark.parametrize(
        "rating,price_level,expected",
        [
            pytest.param(3.5, 2, 0.5 + (2 - 2) * 0.05, id="rating35_price2"),
            pytest.param(3.8, 1, 0.5 + (2 - 1) * 0.05, id="rating38_price1"),
            pytest.param(4.2, 3, 0.5 + (2 - 3) * 0.05, id="rating42_price3"),
        ],
    )
    def test_mid_quality_branch(
        self, rating: float, price_level: int, expected: float
    ) -> None:
        feat = {"rating": rating, "price_level": price_level, "local_factor": 0.0}
        assert EnsembleReranker._tree3_quality(feat) == pytest.approx(expected)

    def test_low_rating(self) -> None:
        feat = {"rating": 2.5, "price_level": 1, "local_factor": 0.5}
        assert EnsembleReranker._tree3_quality(feat) == pytest.approx(0.2)

    def test_boundary_rating_35(self) -> None:
        """Exactly 3.5 IS >= 3.5, enters mid-quality branch."""
        feat = {"rating": 3.5, "price_level": 2, "local_factor": 0.0}
        assert EnsembleReranker._tree3_quality(feat) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Bagging
# ---------------------------------------------------------------------------


class TestBagging:
    """Simple average of the 3 tree scores."""

    def test_equal_scores(self) -> None:
        assert EnsembleReranker._bagging(0.6, 0.6, 0.6) == pytest.approx(0.6)

    def test_mixed_scores(self) -> None:
        # (0.9 + 0.5 + 0.2) / 3 = 1.6 / 3 = 0.5333...
        assert EnsembleReranker._bagging(0.9, 0.5, 0.2) == pytest.approx(1.6 / 3.0)

    def test_zero_scores(self) -> None:
        assert EnsembleReranker._bagging(0.0, 0.0, 0.0) == pytest.approx(0.0)

    def test_all_ones(self) -> None:
        assert EnsembleReranker._bagging(1.0, 1.0, 1.0) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Boosting F1: Fairness correction
# ---------------------------------------------------------------------------


class TestBoostingF1:
    """Fairness correction: penalizes candidates with very low local_factor."""

    def test_low_local_factor_penalty(self) -> None:
        """local_factor < 0.1 → Δ1 = -0.15, applied = η × -0.15 = -0.045."""
        f1, delta = EnsembleReranker._boosting_f1(s_bag=0.6, local_factor=0.05)
        assert delta == pytest.approx(-0.045)
        assert f1 == pytest.approx(0.6 - 0.045)

    def test_boundary_local_factor_01(self) -> None:
        """local_factor == 0.1 is NOT < 0.1, so no penalty."""
        f1, delta = EnsembleReranker._boosting_f1(s_bag=0.6, local_factor=0.1)
        assert delta == pytest.approx(0.0)
        assert f1 == pytest.approx(0.6)

    def test_high_local_factor_no_penalty(self) -> None:
        f1, delta = EnsembleReranker._boosting_f1(s_bag=0.7, local_factor=0.8)
        assert delta == pytest.approx(0.0)
        assert f1 == pytest.approx(0.7)

    def test_penalty_applied_to_score(self) -> None:
        """Verify the correction is properly applied: F1 = s_bag + applied_delta."""
        f1, delta = EnsembleReranker._boosting_f1(s_bag=0.5, local_factor=0.0)
        assert f1 == pytest.approx(0.5 + delta)


# ---------------------------------------------------------------------------
# Boosting F2: Accessibility correction
# ---------------------------------------------------------------------------


class TestBoostingF2:
    """Accessibility correction: rewards wheelchair-accessible venues."""

    def test_wheelchair_accessible_bonus(self) -> None:
        """wheelchairAccessibleEntrance=True → Δ2 = +0.10, applied = 0.03."""
        c = make_candidate(
            accessibility_options={"wheelchairAccessibleEntrance": True}
        )
        f2, delta = EnsembleReranker._boosting_f2(f1=0.6, candidate=c)
        assert delta == pytest.approx(0.03)
        assert f2 == pytest.approx(0.63)

    def test_not_accessible_no_bonus(self) -> None:
        c = make_candidate(accessibility_options={})
        f2, delta = EnsembleReranker._boosting_f2(f1=0.6, candidate=c)
        assert delta == pytest.approx(0.0)
        assert f2 == pytest.approx(0.6)

    def test_explicit_false_no_bonus(self) -> None:
        c = make_candidate(
            accessibility_options={"wheelchairAccessibleEntrance": False}
        )
        f2, delta = EnsembleReranker._boosting_f2(f1=0.6, candidate=c)
        assert delta == pytest.approx(0.0)
        assert f2 == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# Final Score Clipping
# ---------------------------------------------------------------------------


class TestFinalScoreClipping:
    """Clip F2 to [0.0, 1.0]."""

    def test_above_1_clips(self) -> None:
        assert EnsembleReranker._compute_final_score(1.5) == pytest.approx(1.0)

    def test_below_0_clips(self) -> None:
        assert EnsembleReranker._compute_final_score(-0.2) == pytest.approx(0.0)

    def test_exactly_1(self) -> None:
        assert EnsembleReranker._compute_final_score(1.0) == pytest.approx(1.0)

    def test_exactly_0(self) -> None:
        assert EnsembleReranker._compute_final_score(0.0) == pytest.approx(0.0)

    def test_normal_value_passthrough(self) -> None:
        assert EnsembleReranker._compute_final_score(0.72) == pytest.approx(0.72)


# ---------------------------------------------------------------------------
# Full Pipeline: End-to-end tests
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """Single candidate produces all ScoreBreakdown fields correctly."""

    def test_single_candidate_full_breakdown(self) -> None:
        """Verify all 8 ScoreBreakdown fields for a known candidate."""
        c = make_candidate(
            place_id="ChIJ001",
            rating=4.6,
            price_level=2,
            local_factor=0.8,
            open_now=True,
            route_context=RouteContext(distance_meters=200),
            accessibility_options={},
        )
        feat = {
            "local_factor": 0.8,
            "is_open_now": 1,
            "distance_meters": 200,
            "rating": 4.6,
            "price_level": 2,
        }

        candidates, breakdowns = reranker.rerank([c], [feat])

        assert len(candidates) == 1
        assert len(breakdowns) == 1

        b = breakdowns[0]

        # Tree 1: local_factor>0.6 & is_open=1 → 0.9
        assert b.tree1_locality == pytest.approx(0.9)
        # Tree 2: distance<300 → 0.9
        assert b.tree2_proximity == pytest.approx(0.9)
        # Tree 3: rating>=4.5 & price<=2 → 0.85 + 0.8*0.15 = 0.97
        assert b.tree3_quality == pytest.approx(0.97)
        # Bagging: (0.9 + 0.9 + 0.97) / 3 = 0.92333...
        assert b.s_bag == pytest.approx((0.9 + 0.9 + 0.97) / 3.0)
        # Boosting F1: local_factor=0.8 >= 0.1 → delta=0.0
        assert b.delta1_fairness == pytest.approx(0.0)
        # Boosting F2: not wheelchair accessible → delta=0.0
        assert b.delta2_access == pytest.approx(0.0)
        # Final: no clipping needed, unclipped = 0.92333...
        assert b.final_score == pytest.approx((0.9 + 0.9 + 0.97) / 3.0)
        # Rank
        assert b.rank == 1

    def test_single_candidate_with_penalties_and_bonus(self) -> None:
        """Candidate with low local_factor + wheelchair access."""
        c = make_candidate(
            place_id="ChIJ002",
            rating=3.8,
            price_level=1,
            local_factor=0.05,
            open_now=False,
            route_context=RouteContext(distance_meters=1500),
            accessibility_options={"wheelchairAccessibleEntrance": True},
        )
        feat = {
            "local_factor": 0.05,
            "is_open_now": 0,
            "distance_meters": 1500,
            "rating": 3.8,
            "price_level": 1,
        }

        candidates, breakdowns = reranker.rerank([c], [feat])
        b = breakdowns[0]

        # Tree 1: local_factor=0.05 <= 0.3 → 0.2
        assert b.tree1_locality == pytest.approx(0.2)
        # Tree 2: distance=1500 in [800, 2000) → 0.4 + 0.05*0.2 = 0.41
        assert b.tree2_proximity == pytest.approx(0.41)
        # Tree 3: rating=3.8 >= 3.5 → 0.5 + (2-1)*0.05 = 0.55
        assert b.tree3_quality == pytest.approx(0.55)
        # Bagging: (0.2 + 0.41 + 0.55) / 3 = 0.38667
        expected_bag = (0.2 + 0.41 + 0.55) / 3.0
        assert b.s_bag == pytest.approx(expected_bag)
        # Boosting F1: local_factor=0.05 < 0.1 → delta = -0.045
        assert b.delta1_fairness == pytest.approx(-0.045)
        # Boosting F2: wheelchair → delta = +0.03
        assert b.delta2_access == pytest.approx(0.03)
        # Final: expected_bag - 0.045 + 0.03
        expected_final = expected_bag - 0.045 + 0.03
        assert b.final_score == pytest.approx(expected_final)

    def test_score_clipping_in_pipeline_high(self) -> None:
        """Maximum possible pipeline score is ~0.9633, which does not clip.

        Theoretical max: tree1=0.9, tree2=0.9, tree3=1.0 → bag=0.9333
        + accessibility bonus 0.03 = 0.9633. Clipping never fires in practice,
        but _compute_final_score still guards against it (see TestFinalScoreClipping).
        """
        c = make_candidate(
            place_id="ChIJ003",
            rating=5.0,
            price_level=0,
            local_factor=1.0,
            open_now=True,
            route_context=RouteContext(distance_meters=100),
            accessibility_options={"wheelchairAccessibleEntrance": True},
        )
        feat = {
            "local_factor": 1.0,
            "is_open_now": 1,
            "distance_meters": 100,
            "rating": 5.0,
            "price_level": 0,
        }

        _, breakdowns = reranker.rerank([c], [feat])
        b = breakdowns[0]

        # Max possible: (0.9+0.9+1.0)/3 + 0.03 = 0.9633
        assert b.final_score == pytest.approx((0.9 + 0.9 + 1.0) / 3.0 + 0.03)
        assert b.final_score <= 1.0

    def test_score_clipping_in_pipeline_low(self) -> None:
        """Construct a scenario where fairness penalty drives score near 0."""
        c = make_candidate(
            place_id="ChIJ004",
            rating=2.0,
            price_level=4,
            local_factor=0.0,
            open_now=False,
            route_context=RouteContext(distance_meters=5000),
            accessibility_options={},
        )
        feat = {
            "local_factor": 0.0,
            "is_open_now": 0,
            "distance_meters": 5000,
            "rating": 2.0,
            "price_level": 4,
        }

        _, breakdowns = reranker.rerank([c], [feat])
        b = breakdowns[0]

        # Tree 1: 0.2, Tree 2: 0.15, Tree 3: 0.2
        # bag = (0.2 + 0.15 + 0.2) / 3 = 0.1833
        # F1: 0.1833 - 0.045 = 0.1383
        # F2: no accessibility bonus = 0.1383
        # clipped = 0.1383
        assert b.final_score > 0.0
        assert b.final_score <= 1.0


# ---------------------------------------------------------------------------
# Ranking and Sorting
# ---------------------------------------------------------------------------


class TestRanking:
    """Multiple candidates sorted by final_score descending with 1-based ranks."""

    def test_three_candidates_sorted(self) -> None:
        """Three candidates with clearly different scores."""
        c1 = make_candidate(
            place_id="ChIJa",
            rating=4.6, price_level=2, local_factor=0.8,
            open_now=True, route_context=RouteContext(distance_meters=200),
            accessibility_options={},
        )
        c2 = make_candidate(
            place_id="ChIJb",
            rating=3.0, price_level=4, local_factor=0.1,
            open_now=False, route_context=RouteContext(distance_meters=3000),
            accessibility_options={},
        )
        c3 = make_candidate(
            place_id="ChIJc",
            rating=4.0, price_level=1, local_factor=0.5,
            open_now=True, route_context=RouteContext(distance_meters=600),
            accessibility_options={"wheelchairAccessibleEntrance": True},
        )

        features = [
            {"local_factor": 0.8, "is_open_now": 1, "distance_meters": 200, "rating": 4.6, "price_level": 2},
            {"local_factor": 0.1, "is_open_now": 0, "distance_meters": 3000, "rating": 3.0, "price_level": 4},
            {"local_factor": 0.5, "is_open_now": 1, "distance_meters": 600, "rating": 4.0, "price_level": 1},
        ]

        sorted_candidates, breakdowns = reranker.rerank([c1, c2, c3], features)

        assert len(sorted_candidates) == 3
        # Scores should be descending
        assert breakdowns[0].final_score >= breakdowns[1].final_score
        assert breakdowns[1].final_score >= breakdowns[2].final_score
        # Ranks
        assert breakdowns[0].rank == 1
        assert breakdowns[1].rank == 2
        assert breakdowns[2].rank == 3
        # Best candidate should be c1 (high rating, close, high local_factor)
        assert sorted_candidates[0].place_id == "ChIJa"

    def test_stable_sort_for_equal_scores(self) -> None:
        """Identical candidates preserve original order (Python stable sort)."""
        c1 = make_candidate(place_id="ChIJs1", local_factor=0.5, rating=4.0, price_level=2,
                            route_context=RouteContext(distance_meters=500), open_now=True,
                            accessibility_options={})
        c2 = make_candidate(place_id="ChIJs2", local_factor=0.5, rating=4.0, price_level=2,
                            route_context=RouteContext(distance_meters=500), open_now=True,
                            accessibility_options={})

        feat = {"local_factor": 0.5, "is_open_now": 1, "distance_meters": 500, "rating": 4.0, "price_level": 2}

        sorted_candidates, breakdowns = reranker.rerank([c1, c2], [feat, feat])

        assert breakdowns[0].final_score == breakdowns[1].final_score
        # Stable sort preserves original order
        assert sorted_candidates[0].place_id == "ChIJs1"
        assert sorted_candidates[1].place_id == "ChIJs2"


# ---------------------------------------------------------------------------
# Empty Input
# ---------------------------------------------------------------------------


class TestEmptyInput:
    """Empty candidate list returns empty results."""

    def test_empty_list(self) -> None:
        sorted_candidates, breakdowns = reranker.rerank([], [])
        assert sorted_candidates == []
        assert breakdowns == []


# ---------------------------------------------------------------------------
# Combined Scenario: 5 candidates with mixed features
# ---------------------------------------------------------------------------


class TestCombinedScenario:
    """5 candidates with mixed features — verify ranking order."""

    def test_five_candidates_ranked(self) -> None:
        candidates = [
            make_candidate(
                place_id="ChIJ001",
                display_name="Best Local",
                rating=4.8, price_level=1, local_factor=0.9,
                open_now=True, route_context=RouteContext(distance_meters=150),
                accessibility_options={"wheelchairAccessibleEntrance": True},
            ),
            make_candidate(
                place_id="ChIJ002",
                display_name="Close Chain",
                rating=4.0, price_level=2, local_factor=0.2,
                open_now=True, route_context=RouteContext(distance_meters=250),
                accessibility_options={},
            ),
            make_candidate(
                place_id="ChIJ003",
                display_name="Far Local",
                rating=4.5, price_level=2, local_factor=0.85,
                open_now=False, route_context=RouteContext(distance_meters=1800),
                accessibility_options={},
            ),
            make_candidate(
                place_id="ChIJ004",
                display_name="Poor Distant",
                rating=2.5, price_level=4, local_factor=0.05,
                open_now=False, route_context=RouteContext(distance_meters=4000),
                accessibility_options={},
            ),
            make_candidate(
                place_id="ChIJ005",
                display_name="Mid Accessible",
                rating=4.2, price_level=2, local_factor=0.5,
                open_now=True, route_context=RouteContext(distance_meters=700),
                accessibility_options={"wheelchairAccessibleEntrance": True},
            ),
        ]

        features = [
            {"local_factor": 0.9, "is_open_now": 1, "distance_meters": 150, "rating": 4.8, "price_level": 1},
            {"local_factor": 0.2, "is_open_now": 1, "distance_meters": 250, "rating": 4.0, "price_level": 2},
            {"local_factor": 0.85, "is_open_now": 0, "distance_meters": 1800, "rating": 4.5, "price_level": 2},
            {"local_factor": 0.05, "is_open_now": 0, "distance_meters": 4000, "rating": 2.5, "price_level": 4},
            {"local_factor": 0.5, "is_open_now": 1, "distance_meters": 700, "rating": 4.2, "price_level": 2},
        ]

        sorted_candidates, breakdowns = reranker.rerank(candidates, features)

        assert len(sorted_candidates) == 5
        assert len(breakdowns) == 5

        # Verify descending scores
        for i in range(len(breakdowns) - 1):
            assert breakdowns[i].final_score >= breakdowns[i + 1].final_score

        # Verify ranks
        for i, b in enumerate(breakdowns):
            assert b.rank == i + 1

        # Best should be "Best Local" (high everything + accessibility bonus)
        assert sorted_candidates[0].place_id == "ChIJ001"
        # Worst should be "Poor Distant"
        assert sorted_candidates[-1].place_id == "ChIJ004"


# ---------------------------------------------------------------------------
# ScoreBreakdown Serialization
# ---------------------------------------------------------------------------


class TestScoreBreakdownSerialization:
    """model_dump() produces correct JSON shape with all 8 fields."""

    def test_model_dump_has_all_fields(self) -> None:
        b = ScoreBreakdown(
            tree1_locality=0.9,
            tree2_proximity=0.8,
            tree3_quality=0.7,
            s_bag=0.8,
            delta1_fairness=-0.045,
            delta2_access=0.03,
            final_score=0.785,
            rank=1,
        )
        dump = b.model_dump()

        expected_keys = {
            "tree1_locality",
            "tree2_proximity",
            "tree3_quality",
            "s_bag",
            "delta1_fairness",
            "delta2_access",
            "final_score",
            "rank",
        }
        assert set(dump.keys()) == expected_keys

    def test_model_dump_json_shape(self) -> None:
        b = ScoreBreakdown(
            tree1_locality=0.9,
            tree2_proximity=0.8,
            tree3_quality=0.7,
            s_bag=0.8,
            delta1_fairness=-0.045,
            delta2_access=0.03,
            final_score=0.785,
            rank=1,
        )
        json_str = b.model_dump_json()
        import json

        parsed = json.loads(json_str)
        assert parsed["tree1_locality"] == pytest.approx(0.9)
        assert parsed["rank"] == 1
        assert parsed["final_score"] == pytest.approx(0.785)

    def test_pipeline_breakdown_serializable(self) -> None:
        """Verify a real pipeline ScoreBreakdown serializes correctly."""
        c = make_candidate(
            place_id="ChIJser",
            rating=4.6, price_level=2, local_factor=0.8,
            open_now=True, route_context=RouteContext(distance_meters=200),
            accessibility_options={},
        )
        feat = {
            "local_factor": 0.8, "is_open_now": 1, "distance_meters": 200,
            "rating": 4.6, "price_level": 2,
        }

        _, breakdowns = reranker.rerank([c], [feat])
        dump = breakdowns[0].model_dump()

        assert len(dump) == 8
        assert dump["rank"] == 1
        assert isinstance(dump["final_score"], float)
