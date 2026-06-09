"""Tests for M001 fixes including geographic boundary, concept match, and gate tiers."""

from __future__ import annotations
import pytest
from agents.services.place_recommendation_service import (
    PlaceRecommendationService,
    _apply_geographic_boundary_filter,
)
from agents.ranking.feature_extractor import FeatureExtractor, haversine
from app.models.places import PlaceCandidate, HAM_NINH_CENTER
from app.models.request import LatLng

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
    
    kept, removed = _apply_geographic_boundary_filter([near, far])
    assert len(kept) == 1
    assert kept[0].display_name == "Near Place"
    assert removed == 1

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
    assert "đáng cân nhắc cho nhóm đi cùng trẻ em" in suitability_safe.primary_reason_vi

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

