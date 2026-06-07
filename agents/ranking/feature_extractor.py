"""Pure-Python feature extractor for place candidates.

Computes 6 features from a PlaceCandidate + query string + optional user location:
- rating, distance_meters, price_level, is_open_now, local_factor, category_match

All return values are float. Null fields use documented defaults.
"""

from __future__ import annotations

import math
import re

from app.models.places import DEFAULT_SEARCH_RADIUS_METERS, PlaceCandidate
from app.models.request import LatLng

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
            "category_match": self._category_match(candidate, query),
        }

    # -- individual feature extractors ---------------------------------------

    @staticmethod
    def _rating(candidate: PlaceCandidate) -> float:
        """Rating in [1.0–5.0]. Defaults to 3.5 when None."""
        return float(candidate.rating) if candidate.rating is not None else _DEFAULT_RATING

    @staticmethod
    def _distance_meters(
        candidate: PlaceCandidate,
        user_location: LatLng | None,
    ) -> float:
        """Distance in metres.

        Resolution order:
        1. candidate.route_context.distance_meters (cast to float)
        2. haversine(candidate.location, user_location) if both present
        3. DEFAULT_SEARCH_RADIUS_METERS (5000.0)
        """
        # 1. Route context distance (preferred — already computed)
        if candidate.route_context is not None and candidate.route_context.distance_meters is not None:
            return float(candidate.route_context.distance_meters)

        # 2. Haversine from candidate location + user location
        if candidate.location is not None and user_location is not None:
            return haversine(
                user_location.lat,
                user_location.lng,
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
    def _category_match(candidate: PlaceCandidate, query: str) -> float:
        """Keyword overlap between query tokens and candidate type tokens.

        Tokenises query on non-alphanumeric characters, tokenises each type
        string on underscores and non-alphanumeric characters. Score =
        ``len(intersection) / max(len(query_tokens), 1)``, clipped to [0.0, 1.0].
        """
        query_tokens = set(re.split(r"[^a-zA-Z0-9]+", query.lower())) - {""}
        if not query_tokens:
            return 0.0

        type_tokens: set[str] = set()
        for t in candidate.types:
            type_tokens.update(re.split(r"[_\W]+", t.lower()))
        type_tokens.discard("")

        intersection = query_tokens & type_tokens
        score = len(intersection) / max(len(query_tokens), 1)
        return max(0.0, min(1.0, score))
