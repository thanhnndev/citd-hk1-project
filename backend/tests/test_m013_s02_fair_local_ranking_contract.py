"""M013/S02 fair local ranking contract tests.

Proves the full mocked /chat path preserves deterministic S01 behavior
plus S02 fairness balancing and metadata audit semantics.

Covers: mixed local/nonlocal candidates, insufficient local supply,
missing local_factor metadata, and injection-like display names.
"""

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
from agents.graph.agent_service import AgentService
from agents.services.place_recommendation_service import PlaceRecommendationService


def _mock_places_tool(candidates: list[PlaceCandidate], status: PlaceToolStatus = PlaceToolStatus.OK) -> AsyncMock:
    """Build a mocked places_tool returning the given candidates."""
    places_tool = AsyncMock()
    places_tool.text_search.return_value = PlaceToolResponse(
        status=status,
        source=PlaceToolSource.MOCK,
        candidates=candidates,
        request=PlaceSearchRequest(query="test"),
        retrieved_at=datetime.now(UTC),
    )
    return places_tool


def _make_service(places_tool: AsyncMock) -> AgentService:
    """Build an AgentService with the mocked places tool and no retriever."""
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    return AgentService(retriever=None, place_recommendation_service=recommender, checkpoint_mode="test")


# ---------------------------------------------------------------------------
# Contract 1 — Mixed local/nonlocal: top-5 satisfies ≥40% local ratio
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mixed_local_nonlocal_top5_meets_ratio():
    """Mixed candidate pool must produce ≥40% local in top-5 when supply allows."""
    candidates = [
        PlaceCandidate(place_id="places/c1", display_name="Chain A", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c2", display_name="Chain B", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c3", display_name="Chain C", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c4", display_name="Chain D", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c5", display_name="Chain E", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/l1", display_name="Local Quán 1", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/l2", display_name="Local Quán 2", local_factor=0.8, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    places_tool = _mock_places_tool(candidates)
    service = _make_service(places_tool)

    response = await service.answer(session_id="s-mixed", message="tìm nhà hàng", language="vi")

    # S01 boundaries
    assert response.citations == []
    assert response.intent == "place_recommendation"

    # S02 fairness
    audit = response.fairness_audit
    assert audit is not None
    top5 = response.places[:5]
    local_in_top5 = sum(1 for p in top5 if (p.local_factor or 0.0) >= 0.6)
    ratio = local_in_top5 / len(top5) if top5 else 0.0
    assert ratio >= 0.4, f"top5_local_ratio={ratio} < 0.4"
    assert "insufficient_local_candidates" not in audit.warnings


# ---------------------------------------------------------------------------
# Contract 2 — Insufficient local supply: warning emitted, no crash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_insufficient_local_supply_warning():
    """Only 1 local candidate in a 6+ pool — cannot meet 40% target."""
    candidates = [
        PlaceCandidate(place_id="places/l1", display_name="Local Only", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c1", display_name="Chain A", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c2", display_name="Chain B", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c3", display_name="Chain C", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c4", display_name="Chain D", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c5", display_name="Chain E", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    places_tool = _mock_places_tool(candidates)
    service = _make_service(places_tool)

    response = await service.answer(session_id="s-insufficient", message="tìm nhà hàng", language="vi")

    audit = response.fairness_audit
    assert audit is not None
    assert "insufficient_local_candidates" in audit.warnings
    # No crash — response still valid
    assert response.citations == []
    assert response.places  # still returns results
    # Best effort: the 1 local should be in top-5
    top5 = response.places[:5]
    assert any((p.local_factor or 0.0) >= 0.6 for p in top5)


# ---------------------------------------------------------------------------
# Contract 3 — Missing local_factor metadata: warning emitted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_local_factor_metadata_warning():
    """Candidates with local_factor=None increment missing count and emit warning."""
    candidates = [
        PlaceCandidate(place_id="places/a", display_name="A", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/b", display_name="B", local_factor=None, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c", display_name="C", local_factor=None, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/d", display_name="D", local_factor=None, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    places_tool = _mock_places_tool(candidates)
    service = _make_service(places_tool)

    response = await service.answer(session_id="s-missing-factor", message="tìm nhà hàng", language="vi")

    audit = response.fairness_audit
    assert audit is not None
    assert audit.missing_local_factor_count >= 3
    assert "missing_local_factor_metadata" in audit.warnings


# ---------------------------------------------------------------------------
# Contract 4 — Injection-like display names: no naming drift
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_injection_display_names_no_drift():
    """Display names with injection-like content must not leak outside places."""
    candidates = [
        PlaceCandidate(
            place_id="places/inject",
            display_name="Evil Place <script>alert('xss')</script> Hàm Ninh Official",
            local_factor=0.9,
            types=["restaurant"],
            location=LatLng(lat=10.18, lng=104.05),
        ),
        PlaceCandidate(
            place_id="places/normal",
            display_name="Normal Cafe",
            local_factor=0.1,
            types=["cafe"],
            location=LatLng(lat=10.18, lng=104.05),
        ),
    ]
    places_tool = _mock_places_tool(candidates)
    service = _make_service(places_tool)

    response = await service.answer(session_id="s-inject", message="tìm nhà hàng", language="vi")

    # Message must only reference display names from actual results
    for place in response.places:
        # display_name is present in message (from _message_for_status)
        assert place.display_name in response.message, (
            f"Message should reference returned place '{place.display_name}'"
        )

    # No invented place names
    for forbidden in ("Dương Đông", "Phú Quốc Center", "Invented"):
        assert forbidden not in response.message, f"Message should not contain invented name '{forbidden}'"

    # S01 boundaries
    assert response.citations == []


# ---------------------------------------------------------------------------
# Contract 5 — S01 boundaries preserved throughout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_s01_boundaries_citations_empty_rag_not_called():
    """All S02 paths must keep citations=[] and not call retriever."""
    candidates = [
        PlaceCandidate(place_id="places/a", display_name="A", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/b", display_name="B", local_factor=0.8, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c", display_name="C", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    places_tool = _mock_places_tool(candidates)
    retriever = AsyncMock()
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    service = AgentService(retriever=retriever, place_recommendation_service=recommender, checkpoint_mode="test")

    response = await service.answer(session_id="s-s01", message="tìm nhà hàng", language="vi")

    retriever.search_with_citations.assert_not_called()
    assert response.citations == []
    assert response.intent == "place_recommendation"


# ---------------------------------------------------------------------------
# Contract 6 — Fairness audit fields are bounded and serializable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fairness_audit_bounded_and_serializable():
    """Fairness audit must have bounded, serializable fields — no secrets."""
    candidates = [
        PlaceCandidate(place_id="places/a", display_name="A", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/b", display_name="B", local_factor=0.8, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c", display_name="C", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/d", display_name="D", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/e", display_name="E", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    places_tool = _mock_places_tool(candidates)
    service = _make_service(places_tool)

    response = await service.answer(session_id="s-bounded", message="tìm nhà hàng", language="vi")

    audit = response.fairness_audit
    assert audit is not None

    # Bounded fields
    assert 0.0 <= audit.top5_local_ratio <= 1.0
    assert audit.candidate_count >= 0
    assert audit.result_count >= 0
    assert audit.missing_local_factor_count >= 0
    assert len(audit.provider_status) <= 64

    # Serializable
    dump = audit.model_dump_json()
    assert "api_key" not in dump.lower()
    assert "secret" not in dump.lower()
    assert "raw_provider" not in dump.lower()

    # Warning codes from closed vocabulary
    from app.models.places import FairnessWarningType
    allowed = {w.value for w in FairnessWarningType}
    for w in audit.warnings:
        assert w in allowed, f"Unknown warning code: {w}"


# ---------------------------------------------------------------------------
# Contract 7 — Message names only returned display_name values
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_message_names_only_returned_display_names():
    """Response message must reference only PlaceResult.display_name values."""
    candidates = [
        PlaceCandidate(place_id="places/quan-a", display_name="Quán A Hàm Ninh", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/quan-b", display_name="Quán B Biển Xanh", local_factor=0.8, types=["seafood_restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    places_tool = _mock_places_tool(candidates)
    service = _make_service(places_tool)

    response = await service.answer(session_id="s-names", message="tìm quán ăn", language="vi")

    # Message must reference the actual display names
    assert "Quán A Hàm Ninh" in response.message
    assert "Quán B Biển Xanh" in response.message

    # No invented names
    for fake in ("Nhà hàng Sao Biển", "Quán C", "Fake Restaurant"):
        assert fake not in response.message, f"Message should not contain '{fake}'"


# ---------------------------------------------------------------------------
# Contract 8 — Warning codes match the scenario
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_warning_codes_match_scenario():
    """Each scenario must produce the correct warning code(s)."""
    # Scenario: provider non-OK
    places_tool = _mock_places_tool([], status=PlaceToolStatus.UPSTREAM_ERROR)
    service = _make_service(places_tool)
    response = await service.answer(session_id="s-warn-provider", message="tìm nhà hàng", language="vi")
    assert response.fairness_audit is not None
    assert "provider_non_ok" in response.fairness_audit.warnings

    # Scenario: insufficient locals
    candidates = [
        PlaceCandidate(place_id="places/l1", display_name="Local", local_factor=0.9, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c1", display_name="C1", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c2", display_name="C2", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c3", display_name="C3", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c4", display_name="C4", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
        PlaceCandidate(place_id="places/c5", display_name="C5", local_factor=0.1, types=["restaurant"], location=LatLng(lat=10.18, lng=104.05)),
    ]
    places_tool = _mock_places_tool(candidates)
    service = _make_service(places_tool)
    response = await service.answer(session_id="s-warn-insufficient", message="tìm nhà hàng", language="vi")
    assert response.fairness_audit is not None
    assert "insufficient_local_candidates" in response.fairness_audit.warnings
    # Should NOT have provider_non_ok since provider is OK
    assert "provider_non_ok" not in response.fairness_audit.warnings
