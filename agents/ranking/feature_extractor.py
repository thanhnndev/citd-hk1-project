"""Pure-Python feature extractor for place candidates.

Computes 6 features from a PlaceCandidate + query string + optional user location:
- rating, distance_meters, price_level, is_open_now, local_factor, category_match

All return values are float. Null fields use documented defaults.
"""

from __future__ import annotations

import math
from typing import Any

from app.models.places import DEFAULT_SEARCH_RADIUS_METERS, HAM_NINH_CENTER, PlaceCandidate
from app.models.request import LatLng

# ---------------------------------------------------------------------------
# Cross-lingual concept → Google Place type mapping
# ---------------------------------------------------------------------------
# Maps Vietnamese (and English) query concepts to Google Place types.
# Used by _category_match to bridge the gap between Vietnamese queries
# and English-only type tokens from the Google Places API.

QUERY_CONCEPT_TYPE_MAP: dict[tuple[str, ...], set[str]] = {
    # Children / family
    ("trẻ em", "tre em", "trẻ nhỏ", "tre nho", "em bé", "em be", "con nhỏ",
     "con nho", "gia đình", "gia dinh", "kids", "children", "child", "family"): {
        "amusement_park", "museum", "park", "zoo", "aquarium", "tourist_attraction",
        "playground", "amusement_center",
    },
    # Seafood / food
    ("hải sản", "hai san", "quán", "quan", "nhà hàng", "nha hang", "ăn", "an ",
     "seafood", "food", "restaurant", "ẩm thực", "am thuc", "đồ ăn", "do an"): {
        "restaurant", "seafood_restaurant", "vietnamese_restaurant", "food",
        "meal_takeaway", "meal_delivery",
    },
    # Coffee / cafe
    ("cà phê", "ca phe", "cafe", "coffee", "quán cf", "quan cf"): {
        "cafe", "coffee_shop",
    },
    # Accommodation / lodging
    ("khách sạn", "khach san", "homestay", "hotel", "nhà nghỉ", "nha nghi",
     "resort", "stay", "lodging", "lưu trú", "luu tru"): {
        "lodging", "hotel", "resort", "guest_house", "bed_and_breakfast", "homestay",
    },
    # Sightseeing / visit
    ("tham quan", "thăm", "tham", "ghé", "ghe", "visit", "du lịch", "du lich",
     "điểm đến", "diem den", "explore", "sight"): {
        "tourist_attraction", "park", "museum", "zoo", "aquarium", "amusement_park",
    },
    # Shopping
    ("mua sắm", "mua sam", "chợ", "cho", "shop", "shopping", "market"): {
        "shopping_mall", "store", "market", "supermarket",
    },
}

# Maximum distance (m) from HAM_NINH_CENTER before user_location is
# ignored for proximity scoring.  Prevents remote users from shifting
# the entire ranking toward their faraway position.
_PROXIMITY_GUARD_METERS = 20_000

# ---------------------------------------------------------------------------
# Public haversine function (identical math to _haversine_meters in places_service.py)
# ---------------------------------------------------------------------------


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return great-circle distance in metres between two lat/lng points.

    Uses the Earth radius R = 6_371_000 metres and the standard haversine
    formula with atan2 for numerical stability.
    """
    radius_m = 6_371_000
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(delta_lng / 2) ** 2
    )
    return radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# FeatureExtractor
# ---------------------------------------------------------------------------

# Documented null defaults (see S01 research / boundary map)
_DEFAULT_RATING = 3.5
_DEFAULT_PRICE_LEVEL = 2  # moderate
_DEFAULT_IS_OPEN_NOW = 0
_DEFAULT_LOCAL_FACTOR = 0.5


class FeatureExtractor:
    """Extract a fixed set of 6 numeric features from a PlaceCandidate.

    Feature resolution order for ``distance_meters``:
    1. ``candidate.route_context.distance_meters`` (preferred — already computed
       by ``normalize_place()``).
    2. If None and both ``candidate.location`` and ``user_location`` are present,
       call :func:`haversine` to compute great-circle distance.
    3. Otherwise fall back to ``float(DEFAULT_SEARCH_RADIUS_METERS)`` (5000.0).

    All other features use a documented default when their source field is None.
    """

    def extract(
        self,
        candidate: PlaceCandidate,
        query: str,
        user_location: LatLng | None = None,
        frame: Any | None = None,
    ) -> dict[str, float]:
        """Return 6 features as ``dict[str, float]``.

        Keys: ``rating``, ``distance_meters``, ``price_level``,
        ``is_open_now``, ``local_factor``, ``category_match``.
        """
        return {
            "rating": self._rating(candidate),
            "distance_meters": self._distance_meters(candidate, user_location),
            "price_level": self._price_level(candidate),
            "is_open_now": self._is_open_now(candidate),
            "geo_locality": self._geo_locality(candidate),
            "category_match": self._category_match(candidate, query, frame=frame),
        }

    # -- individual feature extractors ---------------------------------------

    @staticmethod
    def _rating(candidate: PlaceCandidate) -> float:
        """Rating in [1.0–5.0]. Defaults to 3.5 when None."""
        return float(candidate.rating) if candidate.rating is not None else _DEFAULT_RATING

    @staticmethod
    def _effective_origin(user_location: LatLng | None) -> LatLng:
        """Return the origin to use for proximity scoring.

        If user_location is provided but more than _PROXIMITY_GUARD_METERS
        from HAM_NINH_CENTER, fall back to HAM_NINH_CENTER so that remote
        users do not shift the entire ranking toward their faraway position.
        """
        if user_location is None:
            return HAM_NINH_CENTER
        dist_from_center = haversine(
            HAM_NINH_CENTER.lat, HAM_NINH_CENTER.lng,
            user_location.lat, user_location.lng,
        )
        if dist_from_center > _PROXIMITY_GUARD_METERS:
            return HAM_NINH_CENTER
        return user_location

    @staticmethod
    def _distance_meters(
        candidate: PlaceCandidate,
        user_location: LatLng | None,
    ) -> float:
        """Distance in metres.

        Resolution order:
        1. candidate.route_context.distance_meters (cast to float)
        2. haversine(candidate.location, effective_origin) if both present
        3. DEFAULT_SEARCH_RADIUS_METERS (5000.0)

        Proximity guard: if user_location is >20km from Ham Ninh center,
        HAM_NINH_CENTER is used instead so remote users don't shift ranking.
        """
        # 1. Route context distance (preferred — already computed)
        if candidate.route_context is not None and candidate.route_context.distance_meters is not None:
            return float(candidate.route_context.distance_meters)

        # 2. Haversine from candidate location + guarded origin
        if candidate.location is not None:
            origin = FeatureExtractor._effective_origin(user_location)
            return haversine(
                origin.lat,
                origin.lng,
                candidate.location.lat,
                candidate.location.lng,
            )

        # 3. Default search radius
        return float(DEFAULT_SEARCH_RADIUS_METERS)

    @staticmethod
    def _price_level(candidate: PlaceCandidate) -> float:
        """Price level in [0–4]. Defaults to 2 (moderate) when None."""
        return float(candidate.price_level) if candidate.price_level is not None else _DEFAULT_PRICE_LEVEL

    @staticmethod
    def _is_open_now(candidate: PlaceCandidate) -> float:
        """1 if open, 0 if closed or unknown."""
        return float(int(candidate.open_now)) if candidate.open_now is not None else _DEFAULT_IS_OPEN_NOW

    @staticmethod
    def _geo_locality(candidate: PlaceCandidate) -> float:
        """Locality in [0.0-1.0] based on distance from HAM_NINH_CENTER."""
        if candidate.location is None:
            return 0.1

        dist = haversine(
            HAM_NINH_CENTER.lat,
            HAM_NINH_CENTER.lng,
            candidate.location.lat,
            candidate.location.lng,
        )
        if dist <= 1500:
            return 1.0
        elif dist <= 3000:
            return 0.7
        elif dist <= 8000:
            return 0.4
        return 0.1

    @staticmethod
    def _frame_category_match(candidate: PlaceCandidate, frame: Any) -> float:
        """Score based on how well the candidate matches the RecommendationFrame."""
        # Candidate types (lowercased)
        candidate_types = set(t.lower() for t in candidate.types)
        if candidate.primary_type:
            candidate_types.add(candidate.primary_type.lower())

        # Inferred role mapping (mirroring place_recommendation_service._candidate_role)
        from agents.services.place_recommendation_service import _VISIT_TYPES, _EAT_TYPES, _STAY_TYPES
        
        role = "unknown"
        if candidate_types & _STAY_TYPES:
            role = "stay"
        elif candidate_types & _EAT_TYPES:
            role = "eat"
        elif candidate_types & _VISIT_TYPES:
            role = "visit"

        if hasattr(frame, "disallowed_roles") and role in frame.disallowed_roles:
            return 0.0
        if hasattr(frame, "desired_roles") and role in frame.desired_roles:
            goal_to_role = {
                "food": "eat",
                "stay": "stay",
                "itinerary": "visit",
                "cafe": "eat",
            }
            if goal_to_role.get(getattr(frame, "goal", "")) == role:
                return 1.0
            return 0.8
        return 0.2

    @staticmethod
    def _category_match(
        candidate: PlaceCandidate,
        query: str,
        frame: Any | None = None,
    ) -> float:
        """Cross-lingual category match between query and candidate types.

        Strategy:
        1. **Concept matching** — scan the query for Vietnamese/English concept
           phrases defined in QUERY_CONCEPT_TYPE_MAP. If any concept phrase
           matches, check whether the candidate's Google Place types overlap
           with the mapped type set. Score = matched_types / expected_types,
           boosted by a 0.5 base for concept match.
        2. **Token overlap fallback** — if no concept phrase matches, fall
           back to raw token intersection (original behaviour).

        This bridges Vietnamese queries ("trẻ em") to English Place API types
        ("amusement_park") that pure token overlap can never match.
        """
        query_lower = query.lower()

        # Candidate type set (lowercased)
        candidate_types: set[str] = set()
        for t in candidate.types:
            candidate_types.add(t.lower())
        if candidate.primary_type:
            candidate_types.add(candidate.primary_type.lower())

        # 1. Concept matching — check Vietnamese/English concept phrases
        best_concept_score = 0.0
        for concept_phrases, expected_types in QUERY_CONCEPT_TYPE_MAP.items():
            for phrase in concept_phrases:
                if phrase in query_lower:
                    # Found a concept match — calculate type overlap
                    matched = candidate_types & expected_types
                    if matched:
                        # Base 0.5 for concept match + 0.5 * overlap ratio
                        overlap_ratio = len(matched) / max(len(expected_types), 1)
                        score = 0.5 + 0.5 * overlap_ratio
                        best_concept_score = max(best_concept_score, score)
                    break  # Only need one phrase per concept group

        if best_concept_score > 0.0:
            score = min(1.0, best_concept_score)
        else:
            cleaned_query = "".join(c if c.isalnum() else " " for c in query_lower)
            query_tokens = set(cleaned_query.split())
            if not query_tokens:
                score = 0.0
            else:
                type_tokens: set[str] = set()
                for t in candidate.types:
                    cleaned_type = "".join(c if c.isalnum() else " " for c in t.lower())
                    type_tokens.update(cleaned_type.split())
                type_tokens.discard("")

                intersection = query_tokens & type_tokens
                score = len(intersection) / max(len(query_tokens), 1)
                score = max(0.0, min(1.0, score))

        if frame is not None:
            frame_score = FeatureExtractor._frame_category_match(candidate, frame)
            score = score * (0.5 + 0.5 * frame_score)

        return score
