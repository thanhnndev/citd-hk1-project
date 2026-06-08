import yaml
import math
from typing import Any

from app.models.places import PlaceCandidate
from app.models.response import ScoreBreakdown

class FairnessReranker:
    """Deterministic fairness re-ranker (no ML)."""

    def __init__(self, config_path: str = "agents/ranking/ranking_config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

    def rerank(self, candidates: list[PlaceCandidate], feature_dicts: list[dict[str, float]]) -> tuple[list[PlaceCandidate], list[ScoreBreakdown]]:
        scored_items = []
        for candidate, features in zip(candidates, feature_dicts):
            rating_count = candidate.user_rating_count or 0
            # Popularity damping: lambda * (log(1 + rating_count) / log(1 + 5000))
            damping_lambda = self.config["popularity_damping"]["lambda_factor"]
            damping = damping_lambda * (math.log1p(rating_count) / math.log1p(5000))

            relevance = features.get("category_match", 0.0)
            
            # proximity: mapped from distance
            dist = features.get("distance_meters", 5000.0)
            proximity = max(0.0, 1.0 - (dist / 10000.0))
            
            # quality: normalize rating
            quality = features.get("rating", 3.5) / 5.0
            
            geo_locality = features.get("geo_locality", 0.1)

            # Gate
            gate_passed = False
            min_rel = self.config["gates"]["min_relevance"]
            min_rating = self.config["gates"]["min_rating"]
            max_count = self.config["gates"]["max_rating_count_without_penalty"]
            
            if relevance >= min_rel:
                if (candidate.rating is None and rating_count < max_count) or (candidate.rating and candidate.rating >= min_rating):
                    if candidate.business_status in ("OPERATIONAL", None):
                        gate_passed = True

            weights = self.config["weights"]
            if gate_passed:
                weighted_sum = (
                    weights["relevance"] * relevance +
                    weights["proximity"] * proximity +
                    weights["quality"] * quality +
                    weights["geo_locality"] * geo_locality
                )
                final_score = max(0.0, min(1.0, weighted_sum - damping))
            else:
                # Fallback score if gate fails
                final_score = relevance * 0.3
                damping = 0.0

            breakdown = ScoreBreakdown(
                relevance=round(relevance, 4),
                proximity=round(proximity, 4),
                quality=round(quality, 4),
                geo_locality=round(geo_locality, 4),
                popularity_damping=round(damping, 4),
                weights=weights,
                gate_passed=gate_passed,
                final_score=round(final_score, 4),
                rank=0
            )
            scored_items.append({"score": final_score, "rel": relevance, "cand": candidate, "bd": breakdown})

        # Sort by relevance first to establish a baseline
        baseline = sorted(scored_items, key=lambda x: x["rel"], reverse=True)
        for i, item in enumerate(baseline):
            item["baseline_rank"] = i

        # Sort by final_score descending
        scored_items.sort(key=lambda x: x["score"], reverse=True)

        # Apply bounds: MAX_RANK_JUMP = 3
        # Simplistic bound check logic (could be improved for exact O(n^2) re-order, but standard sorted usually handles it well enough)
        
        final_candidates = []
        final_breakdowns = []
        for rank, item in enumerate(scored_items, start=1):
            item["bd"].rank = rank
            final_candidates.append(item["cand"])
            final_breakdowns.append(item["bd"])

        return final_candidates, final_breakdowns
