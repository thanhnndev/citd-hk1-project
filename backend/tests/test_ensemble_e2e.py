"""HTTP-level E2E test for the ensemble pipeline via POST /chat.

Exercises the full chain: POST /chat → AgentService → PlaceRecommendationService
→ FeatureExtractor → EnsembleReranker → ScoreBreakdown → ranked JSON response.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.places import (
    PlaceCandidate,
    PlaceSearchRequest,
    PlaceToolResponse,
    PlaceToolSource,
    PlaceToolStatus,
)
from app.models.request import LatLng
from app.models.response import ScoreBreakdown
from agents.graph.agent_service import AgentService
from agents.services.place_recommendation_service import PlaceRecommendationService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HAM_NINH = LatLng(lat=10.1794, lng=104.0491)


def _local_candidate(
    place_id: str,
    local_factor: float,
    display_name: str,
    rating: float = 4.5,
) -> PlaceCandidate:
    """Build a locally-owned place candidate."""
    return PlaceCandidate(
        place_id=place_id,
        display_name=display_name,
        types=["restaurant", "seafood_restaurant"],
        primary_type="seafood_restaurant",
        location=HAM_NINH.model_copy(),
        local_factor=local_factor,
        rating=rating,
        price_level=2,
        open_now=True,
        business_status="OPERATIONAL",
        google_maps_uri=f"https://maps.example/{place_id}",
    )


def _chain_candidate(
    place_id: str,
    local_factor: float,
    display_name: str,
    rating: float = 4.0,
) -> PlaceCandidate:
    """Build a chain-brand place candidate."""
    return PlaceCandidate(
        place_id=place_id,
        display_name=display_name,
        types=["restaurant"],
        primary_type="restaurant",
        location=HAM_NINH.model_copy(),
        local_factor=local_factor,
        rating=rating,
        price_level=3,
        open_now=True,
        business_status="OPERATIONAL",
        google_maps_uri=f"https://maps.example/{place_id}",
    )


def _assert_valid_score_breakdown(breakdown: dict) -> None:
    """Assert all 8 ensemble schema fields are present and within bounds."""
    required_fields = {
        "tree1_locality", "tree2_proximity", "tree3_quality", "s_bag",
        "delta1_fairness", "delta2_access", "final_score", "rank",
    }
    assert required_fields.issubset(breakdown.keys()), (
        f"ScoreBreakdown missing fields: {required_fields - breakdown.keys()}"
    )
    for field_name in ("tree1_locality", "tree2_proximity", "tree3_quality", "s_bag"):
        assert 0.0 <= breakdown[field_name] <= 1.0, (
            f"{field_name} out of [0,1]: {breakdown[field_name]}"
        )
    assert 0.0 <= breakdown["final_score"] <= 1.0
    assert breakdown["rank"] >= 1
    # final_score must be a real number (not NaN)
    assert breakdown["final_score"] == breakdown["final_score"]


# ---------------------------------------------------------------------------
# E2E Test
# ---------------------------------------------------------------------------

class TestEnsemblePipelineE2E:
    """POST /chat with place-recommendation intent exercises the full ensemble pipeline."""

    def test_post_chat_place_recommendation_returns_ensemble_ranked_places(self, retriever) -> None:
        """Full HTTP chain: POST /chat → AgentService → PlaceRecommendationService
        → FeatureExtractor → EnsembleReranker → ScoreBreakdown → ranked JSON.

        Uses 8 mixed candidates (4 local, 4 chain) to verify:
        - HTTP 200 with place_recommendation intent
        - All 8 places returned with valid ScoreBreakdown
        - ≥40% local-in-top-5 (fairness constraint)
        - Score bounds and rank ordering
        """
        # 1. Build 8 mixed candidates: 4 local (high local_factor), 4 chain (low local_factor)
        candidates = [
            # Local candidates — local_factor 0.7–0.9
            _local_candidate("places/local-1", local_factor=0.90, display_name="Hải Sản Hàm Ninh 1", rating=4.8),
            _local_candidate("places/local-2", local_factor=0.85, display_name="Nhà Hàng Biển Xanh", rating=4.6),
            _local_candidate("places/local-3", local_factor=0.80, display_name="Quán Cồn Khơi", rating=4.5),
            _local_candidate("places/local-4", local_factor=0.70, display_name="Hải Sản Năm Danh", rating=4.3),
            # Chain candidates — local_factor 0.01–0.03
            _chain_candidate("places/chain-1", local_factor=0.03, display_name="Chain Seafood A", rating=4.2),
            _chain_candidate("places/chain-2", local_factor=0.02, display_name="Chain Seafood B", rating=4.1),
            _chain_candidate("places/chain-3", local_factor=0.01, display_name="Chain Seafood C", rating=4.0),
            _chain_candidate("places/chain-4", local_factor=0.01, display_name="Chain Seafood D", rating=3.9),
        ]

        # 2. Mock places_tool.text_search() to return the 8 candidates
        places_tool = AsyncMock()
        places_tool.text_search.return_value = PlaceToolResponse(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.MOCK,
            candidates=candidates,
            request=PlaceSearchRequest(query="hải sản hàm ninh"),
            retrieved_at=datetime.now(UTC),
        )

        # 3. Wire services into app.state — must be done INSIDE the TestClient
        #    context because the lifespan overwrites app.state.agent_service on startup.
        #    We let the lifespan run (loads corpus + retriever), then replace the
        #    agent_service with our mock-backed one before the POST request.
        mock_rec_service = PlaceRecommendationService(places_tool)

        # 4. POST to /chat via TestClient
        with TestClient(app) as client:
            # Override agent_service AFTER lifespan has initialized
            app.state.agent_service = AgentService(
                retriever=retriever,
                place_recommendation_service=mock_rec_service,
                checkpoint_mode="test",
            )

            r = client.post("/chat", json={
                "session_id": "e2e-1",
                "message": "Gợi ý hải sản Hàm Ninh",
                "language": "vi",
            })

        # 5. Assert HTTP-level contract
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        body = r.json()

        # 6. Assert intent detection
        assert body["intent"] == "place_recommendation", (
            f"Expected place_recommendation intent, got: {body['intent']}"
        )

        # 7. Assert places count — all 8 candidates should be returned
        places = body["places"]
        assert len(places) == 8, f"Expected 8 places, got {len(places)}"

        # 8. Assert every place has a valid 8-field ScoreBreakdown
        for i, place in enumerate(places):
            sb = place["score_breakdown"]
            _assert_valid_score_breakdown(sb)
            # final_score in PlaceResult must match ScoreBreakdown.final_score
            assert place["final_score"] == sb["final_score"], (
                f"Place {i}: final_score mismatch ({place['final_score']} != {sb['final_score']})"
            )
            # rank must be 1-based and sequential
            assert sb["rank"] == i + 1, (
                f"Place at index {i}: expected rank {i + 1}, got {sb['rank']}"
            )

        # 9. Fairness constraint: ≥40% of top-5 must be local (local_factor > 0.5)
        local_in_top5 = sum(1 for p in places[:5] if p["local_factor"] > 0.5)
        assert local_in_top5 >= 2, (
            f"Fairness constraint violated: only {local_in_top5}/5 top places have local_factor > 0.5"
        )

        # 10. Score bounds: all final_scores in [0, 1]
        scores = [p["final_score"] for p in places]
        assert all(0.0 <= s <= 1.0 for s in scores), (
            f"final_score out of bounds: {scores}"
        )

        # 11. Rank ordering: scores must be non-increasing (descending by final_score)
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"Rank ordering violated: place {i} score {scores[i]} < place {i+1} score {scores[i+1]}"
            )

        # 12. Session ID echoed back
        assert body["session_id"] == "e2e-1"

        # 13. Latency must be positive
        assert body["latency_ms"] > 0

        # 14. Response message should reference found places
        assert "found" in body["message"].lower() or "hàm ninh" in body["message"].lower()
