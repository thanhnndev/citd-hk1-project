"""Ensemble reranker: 3 decision trees + bagging + boosting.

Transforms feature dicts and PlaceCandidates into ranked results with full
score breakdowns per REQUIREMENTS.md §7.4–7.8.

Pipeline:
  tree1(locality) → tree2(proximity) → tree3(quality)
  → bagging (mean) → boosting_f1 (fairness) → boosting_f2 (accessibility)
  → clip → rank
"""

from __future__ import annotations

from app.models.places import PlaceCandidate
from app.models.response import ScoreBreakdown

LEARNING_RATE = 0.3  # η — used for both boosting corrections


class EnsembleReranker:
    """Pure-computation ensemble reranker.

    Takes a list of PlaceCandidate objects and their corresponding feature
    dicts, scores each through a 3-tree ensemble with bagging and boosting,
    then returns sorted candidates with full ScoreBreakdowns.
    """

    # ------------------------------------------------------------------
    # Decision trees
    # ------------------------------------------------------------------

    @staticmethod
    def _tree1_locality(features: dict) -> float:
        """Tree 1: locality-first decision tree.

        Rewards locally-owned businesses, with an extra boost when open.
        """
        local_factor = features.get("local_factor", 0.0)
        is_open_now = features.get("is_open_now", 0)

        if local_factor > 0.6 and is_open_now == 1:
            return 0.9
        elif local_factor > 0.6:
            return 0.7
        elif local_factor > 0.3:
            return 0.5
        else:
            return 0.2

    @staticmethod
    def _tree2_proximity(features: dict) -> float:
        """Tree 2: proximity-first decision tree.

        Rewards closer venues, modulated by rating and local factor.
        """
        distance = features.get("distance_meters", 9999)
        rating = features.get("rating", 3.0)
        local_factor = features.get("local_factor", 0.0)

        if distance < 300:
            return 0.9
        elif distance < 800:
            return 0.65 + (rating - 3.0) * 0.1
        elif distance < 2000:
            return 0.4 + local_factor * 0.2
        else:
            return 0.15

    @staticmethod
    def _tree3_quality(features: dict) -> float:
        """Tree 3: quality-first decision tree.

        Rewards high-rated, affordable venues with locality bonus.
        """
        rating = features.get("rating", 3.0)
        price_level = features.get("price_level", 2)
        local_factor = features.get("local_factor", 0.0)

        if rating >= 4.5 and price_level <= 2:
            return 0.85 + local_factor * 0.15
        elif rating >= 4.0 and price_level <= 1:
            return 0.75
        elif rating >= 3.5:
            return 0.5 + (2 - price_level) * 0.05
        else:
            return 0.2

    # ------------------------------------------------------------------
    # Ensemble aggregation
    # ------------------------------------------------------------------

    @staticmethod
    def _bagging(t1: float, t2: float, t3: float) -> float:
        """Simple average of the 3 tree scores."""
        return (t1 + t2 + t3) / 3.0

    @staticmethod
    def _boosting_f1(s_bag: float, local_factor: float) -> tuple[float, float]:
        """Boosting stage 1: fairness correction based on local factor.

        Returns (F1, applied_delta1).
        Applied delta = η × Δ1, where Δ1 = -0.15 if local_factor < 0.1 else 0.0.
        """
        raw_delta1 = -0.15 if local_factor < 0.1 else 0.0
        applied_delta1 = LEARNING_RATE * raw_delta1
        f1 = s_bag + applied_delta1
        return f1, applied_delta1

    @staticmethod
    def _boosting_f2(
        f1: float, candidate: PlaceCandidate
    ) -> tuple[float, float]:
        """Boosting stage 2: accessibility correction.

        Returns (F2, applied_delta2).
        Checks candidate.accessibility_options for wheelchair accessibility.
        Applied delta = η × Δ2, where Δ2 = +0.10 if accessible else 0.0.
        """
        is_accessible = candidate.accessibility_options.get(
            "wheelchairAccessibleEntrance", False
        )
        raw_delta2 = 0.10 if is_accessible else 0.0
        applied_delta2 = LEARNING_RATE * raw_delta2
        f2 = f1 + applied_delta2
        return f2, applied_delta2

    @staticmethod
    def _compute_final_score(f2: float) -> float:
        """Clip F2 to [0.0, 1.0]."""
        return max(0.0, min(1.0, f2))

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def rerank(
        self,
        candidates: list[PlaceCandidate],
        features: list[dict[str, float]],
    ) -> tuple[list[PlaceCandidate], list[ScoreBreakdown]]:
        """Rank candidates through the full ensemble pipeline.

        Args:
            candidates: PlaceCandidate objects to score and rank.
            features: Feature dicts aligned 1:1 with candidates (from
                      FeatureExtractor).

        Returns:
            (sorted_candidates, score_breakdowns) sorted by final_score
            descending with stable tie-breaking. Ranks are 1-based.
        """
        results: list[tuple[PlaceCandidate, ScoreBreakdown]] = []

        for candidate, feat in zip(candidates, features):
            # 3 decision trees
            t1 = self._tree1_locality(feat)
            t2 = self._tree2_proximity(feat)
            t3 = self._tree3_quality(feat)

            # Bagging
            s_bag = self._bagging(t1, t2, t3)

            # Boosting stage 1 (fairness)
            f1, applied_delta1 = self._boosting_f1(
                s_bag, feat.get("local_factor", 0.0)
            )

            # Boosting stage 2 (accessibility)
            f2, applied_delta2 = self._boosting_f2(f1, candidate)

            # Final clip
            final_score = self._compute_final_score(f2)

            breakdown = ScoreBreakdown(
                tree1_locality=t1,
                tree2_proximity=t2,
                tree3_quality=t3,
                s_bag=s_bag,
                delta1_fairness=applied_delta1,
                delta2_access=applied_delta2,
                final_score=final_score,
                rank=0,  # assigned after sorting
            )
            results.append((candidate, breakdown))

        # Stable sort by final_score descending
        results.sort(key=lambda pair: pair[1].final_score, reverse=True)

        # Assign 1-based ranks
        score_breakdowns: list[ScoreBreakdown] = []
        sorted_candidates: list[PlaceCandidate] = []
        for i, (candidate, breakdown) in enumerate(results, start=1):
            breakdown.rank = i
            sorted_candidates.append(candidate)
            score_breakdowns.append(breakdown)

        return sorted_candidates, score_breakdowns
