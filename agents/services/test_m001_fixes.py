"""Tests for M001 fixes including geographic boundary, concept match, and gate tiers."""

from __future__ import annotations
import pytest
from agents.services.place_recommendation_service import (
    PlaceRecommendationService,
    _apply_geographic_boundary_filter,
    _infer_included_type,
    _provider_search_query,
)
from agents.ranking.feature_extractor import FeatureExtractor, haversine
from app.models.places import PlaceCandidate, HAM_NINH_CENTER
from app.models.request import LatLng
from agents.tools.places_service import _location
from agents.guardrails.input_guardrails import reject_off_topic
from agents.graph.nodes import (
    _conversational_domain_action,
    conversational_node,
    maps_agent_node,
    requires_user_location_heuristic,
    supervisor_node,
)

def _candidate(name: str, lat: float, lng: float, types: list[str]) -> PlaceCandidate:
    return PlaceCandidate(
        place_id=f"id-{name}",
        display_name=name,
        primary_type=types[0] if types else "restaurant",
        types=types,
        formatted_address="Ham Ninh",
        location=LatLng(lat=lat, lng=lng),
        rating=4.5,
        user_rating_count=50,
        business_status="OPERATIONAL",
    )

def test_geographic_boundary_filter() -> None:
    # Near Ham Ninh: 3km away
    near = _candidate("Near Place", 10.1835, 104.07, ["restaurant"])
    # Far: 15km away
    far = _candidate("Far Place", 10.2835, 104.0497, ["restaurant"])
    # Missing location cannot be verified against the 8km hard boundary.
    missing_location = PlaceCandidate(
        place_id="id-missing",
        display_name="Missing Location Place",
        primary_type="restaurant",
        types=["restaurant"],
        formatted_address="Unknown",
        location=None,
    )
    
    kept, removed = _apply_geographic_boundary_filter([near, far, missing_location])
    assert len(kept) == 1
    assert kept[0].display_name == "Near Place"
    assert removed == 2

def test_google_places_new_location_shape() -> None:
    location = _location({"latitude": HAM_NINH_CENTER.lat, "longitude": HAM_NINH_CENTER.lng})
    assert location is not None
    assert location.lat == HAM_NINH_CENTER.lat
    assert location.lng == HAM_NINH_CENTER.lng

def test_cafe_provider_query_ignores_subjective_preferences() -> None:
    included_type = _infer_included_type("Tìm quán cafe view đẹp ở Hàm Ninh")

    assert included_type == "cafe"
    assert (
        _provider_search_query("Tìm quán cafe view đẹp ở Hàm Ninh", included_type)
        == "quán cà phê Hàm Ninh"
    )

def test_near_named_area_does_not_require_user_location() -> None:
    assert requires_user_location_heuristic("Có quán cà phê nào gần Hàm Ninh không") is False
    assert requires_user_location_heuristic("Có quán cà phê nào gần tôi không") is True

def test_conversational_domain_gate_refuses_general_tasks() -> None:
    assert _conversational_domain_action("Write an email asking for leave", []) == "refuse"
    assert _conversational_domain_action("Tell me about Ham Ninh", []) == "allow"

def test_conversational_domain_gate_clarifies_responsible_travel_without_context() -> None:
    assert _conversational_domain_action("Is it safe for wheelchair users?", []) == "clarify"
    assert _conversational_domain_action(
        "Is it safe for wheelchair users?",
        [{"role": "assistant", "content": "Ham Ninh travel places around Phu Quoc"}],
    ) == "allow"

@pytest.mark.asyncio
async def test_conversational_node_refuses_off_domain_llm_path() -> None:
    result = await conversational_node({
        "session_id": "test-session",
        "message": "Write an email asking for leave",
        "language": "en",
        "history": [],
    })

    assert result["intent"] == "off_topic"
    assert "Ham Ninh/Phu Quoc travel advice" in result["response_text"]

@pytest.mark.asyncio
async def test_input_guardrail_blocks_creative_content_even_when_ham_ninh_is_named() -> None:
    result = await reject_off_topic("tạo 1 bài thơ về Hàm Ninh", llm_client=None)

    assert result.verdict == "blocked"
    assert result.details == "non_advisory_content_generation"

def test_vietnamese_concept_match() -> None:
    candidate = _candidate("Water Park", 10.1835, 104.0497, ["amusement_park"])
    
    # Concept matching for children/kids
    score1 = FeatureExtractor._category_match(candidate, "đi chơi với trẻ em")
    assert score1 >= 0.5
    
    # Token matching fallback
    score2 = FeatureExtractor._category_match(candidate, "amusement park")
    assert score2 > 0.0

def test_proximity_guard_far_user() -> None:
    # User is in Sài Gòn (~300km away)
    far_user = LatLng(lat=10.776, lng=106.700)
    origin = FeatureExtractor._effective_origin(far_user)
    # Proximity guard fallbacks to HAM_NINH_CENTER
    assert origin.lat == HAM_NINH_CENTER.lat
    assert origin.lng == HAM_NINH_CENTER.lng

    # User is close (2km away)
    close_user = LatLng(lat=10.1835, lng=104.06)
    origin_close = FeatureExtractor._effective_origin(close_user)
    assert origin_close.lat == close_user.lat

def test_family_dangerous_places_filter() -> None:
    from agents.services.place_recommendation_service import (
        _build_recommendation_frame,
        _evaluate_candidate_suitability,
    )
    
    # Create request recommendation frame for family
    frame = _build_recommendation_frame("Đi với trẻ em nên ghé đâu?")
    assert frame.audience == "family"
    
    # A safe place: Teddy Bear Museum
    safe_museum = _candidate("Teddy Bear Museum", 10.1835, 104.05, ["museum", "tourist_attraction"])
    suitability_safe = _evaluate_candidate_suitability(safe_museum, frame)
    assert not suitability_safe.disqualified
    assert "có thể cân nhắc cho nhóm đi cùng trẻ em" in suitability_safe.primary_reason_vi

    # A dangerous place: Fairy Waterfall (by type)
    waterfall = _candidate("Fairy Waterfall", 10.1835, 104.05, ["waterfall", "tourist_attraction"])
    suitability_waterfall = _evaluate_candidate_suitability(waterfall, frame)
    assert suitability_waterfall.disqualified
    assert "không phù hợp cho nhóm đi cùng trẻ em" in suitability_waterfall.primary_reason_vi

    # A dangerous place: Suối Đá Bàn (by name keyword)
    suoi_da_ban = _candidate("Khu du lịch sinh thái (Suối Đá Bàn)", 10.1835, 104.05, ["tourist_attraction"])
    suitability_suoi = _evaluate_candidate_suitability(suoi_da_ban, frame)
    assert suitability_suoi.disqualified
    assert "không phù hợp cho nhóm đi cùng trẻ em" in suitability_suoi.primary_reason_vi

@pytest.mark.asyncio
async def test_deictic_decision_followup_without_context_does_not_call_places() -> None:
    state = {
        "session_id": "test-session",
        "message": "Người khuyết tật đi đến đó có được không?",
        "language": "vi",
        "needs_location": False,
        "last_places": [],
    }

    result = await maps_agent_node(state)

    assert result["intent"] == "place_decision_followup"
    assert result["places"] == []


@pytest.mark.asyncio
async def test_supervisor_blocks_places_call_for_existing_place_followup() -> None:
    state = {
        "session_id": "test-session",
        "message": "Người khuyết tật đi đến đó có được không?",
        "language": "vi",
        "intent": "restaurant_search",
        "routing_tier": "strict",
        "guardrail_flags": {},
        "last_places": [{"display_name": "Bè hải sản Tình Biển 2"}],
    }

    result = await supervisor_node(state)

    assert result["next_node"] == "maps_agent"
    assert result["tool_call_allowed"] is False
    assert result["tool_call_reason"] == "decision_followup_existing_places"


@pytest.mark.asyncio
async def test_supervisor_allows_places_call_for_new_discovery() -> None:
    state = {
        "session_id": "test-session",
        "message": "Tìm quán hải sản ở Hàm Ninh",
        "language": "vi",
        "intent": "restaurant_search",
        "routing_tier": "strict",
        "guardrail_flags": {},
        "last_places": [],
    }

    result = await supervisor_node(state)

    assert result["next_node"] == "maps_agent"
    assert result["tool_call_allowed"] is True
    assert result["tool_call_reason"] == "new_place_discovery"
