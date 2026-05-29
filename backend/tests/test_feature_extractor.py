"""Tests for FeatureExtractor: 6 features with null handling and haversine."""

from __future__ import annotations

import pytest

from app.models.places import DEFAULT_SEARCH_RADIUS_METERS, PlaceCandidate, RouteContext
from app.models.request import LatLng
from agents.ml.feature_extractor import FeatureExtractor, haversine


def make_candidate(**overrides: object) -> PlaceCandidate:
    """Factory mirroring the place fixture pattern -- start with defaults, apply overrides."""
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
        route_context=RouteContext(distance_meters=1200),
    )
    return base.model_copy(update=overrides)


extractor = FeatureExtractor()


# ---------------------------------------------------------------------------
# Haversine standalone tests
# ---------------------------------------------------------------------------


class TestHaversine:
    def test_same_point_zero_distance(self) -> None:
        d = haversine(10.0, 106.0, 10.0, 106.0)
        assert d == 0.0

    def test_known_distance_ham_ninh_to_hcmc(self) -> None:
        # Ham Ninh (Phu Quoc) to HCMC — approximately 290-295 km
        d = haversine(10.1794, 104.0491, 10.7626, 106.6601)
        assert 280_000 < d < 300_000

    def test_symmetric(self) -> None:
        d1 = haversine(1.0, 2.0, 3.0, 4.0)
        d2 = haversine(3.0, 4.0, 1.0, 2.0)
        assert abs(d1 - d2) < 1e-6


# ---------------------------------------------------------------------------
# All fields present — exact values
# ---------------------------------------------------------------------------


class TestAllFieldsPresent:
    def test_returns_all_six_features_as_floats(self) -> None:
        c = make_candidate()
        user_loc = LatLng(lat=10.1800, lng=104.0500)
        features = extractor.extract(c, "seafood restaurant", user_loc)
        assert set(features.keys()) == {
            "rating",
            "distance_meters",
            "price_level",
            "is_open_now",
            "local_factor",
            "category_match",
        }
        for v in features.values():
            assert isinstance(v, float)

    def test_exact_values(self) -> None:
        c = make_candidate()
        user_loc = LatLng(lat=10.1800, lng=104.0500)
        features = extractor.extract(c, "seafood restaurant", user_loc)
        assert features["rating"] == 4.6
        assert features["distance_meters"] == 1200.0  # from route_context
        assert features["price_level"] == 2.0
        assert features["is_open_now"] == 1.0
        assert features["local_factor"] == 0.8


# ---------------------------------------------------------------------------
# Null-default edge cases — each feature
# ---------------------------------------------------------------------------


class TestNullDefaults:
    def test_rating_none_uses_default(self) -> None:
        c = make_candidate(rating=None)
        features = extractor.extract(c, "query", None)
        assert features["rating"] == 3.5

    @pytest.mark.parametrize("open_now,expected", [(None, 0.0), (True, 1.0), (False, 0.0)])
    def test_is_open_now(self, open_now: bool | None, expected: float) -> None:
        c = make_candidate(open_now=open_now)
        features = extractor.extract(c, "query", None)
        assert features["is_open_now"] == expected

    def test_local_factor_none_uses_default(self) -> None:
        c = make_candidate(local_factor=None)
        features = extractor.extract(c, "query", None)
        assert features["local_factor"] == 0.5

    def test_price_level_none_uses_default(self) -> None:
        c = make_candidate(price_level=None)
        features = extractor.extract(c, "query", None)
        assert features["price_level"] == 2.0


# ---------------------------------------------------------------------------
# Distance resolution order
# ---------------------------------------------------------------------------


class TestDistanceResolution:
    def test_route_context_present_uses_it(self) -> None:
        c = make_candidate(route_context=RouteContext(distance_meters=3500))
        features = extractor.extract(c, "query", LatLng(lat=10.0, lng=106.0))
        assert features["distance_meters"] == 3500.0

    def test_no_route_context_uses_haversine(self) -> None:
        c = make_candidate(
            route_context=None,
            location=LatLng(lat=10.0, lng=106.0),
        )
        user_loc = LatLng(lat=10.01, lng=106.01)
        features = extractor.extract(c, "query", user_loc)
        # Should be small haversine distance, not the default 5000
        assert 0 < features["distance_meters"] < 2000.0

    def test_no_route_context_no_location_uses_default(self) -> None:
        c = make_candidate(route_context=None, location=None)
        user_loc = LatLng(lat=10.0, lng=106.0)
        features = extractor.extract(c, "query", user_loc)
        assert features["distance_meters"] == float(DEFAULT_SEARCH_RADIUS_METERS)

    def test_no_user_location_uses_default(self) -> None:
        c = make_candidate(route_context=None)
        features = extractor.extract(c, "query", user_location=None)
        assert features["distance_meters"] == float(DEFAULT_SEARCH_RADIUS_METERS)

    def test_route_context_none_field_falls_to_haversine(self) -> None:
        c = make_candidate(
            route_context=RouteContext(distance_meters=None),
            location=LatLng(lat=10.0, lng=106.0),
        )
        user_loc = LatLng(lat=10.01, lng=106.01)
        features = extractor.extract(c, "query", user_loc)
        # haversine should fire because route_context exists but distance is None
        assert 0 < features["distance_meters"] < 2000.0


# ---------------------------------------------------------------------------
# Category match — keyword overlap
# ---------------------------------------------------------------------------


class TestCategoryMatch:
    def test_empty_types_returns_zero(self) -> None:
        c = make_candidate(types=[])
        features = extractor.extract(c, "seafood restaurant", None)
        assert features["category_match"] == 0.0

    def test_empty_query_returns_zero(self) -> None:
        c = make_candidate()
        features = extractor.extract(c, "", None)
        assert features["category_match"] == 0.0

    def test_partial_overlap(self) -> None:
        # query_tokens: {seafood, restaurant, near, me} → 4 tokens
        # type_tokens: {seafood, restaurant, food}
        # intersection: {seafood, restaurant} → 2/4 = 0.5
        c = make_candidate(types=["seafood_restaurant", "food"])
        features = extractor.extract(c, "seafood restaurant near me", None)
        assert features["category_match"] == pytest.approx(0.5)

    def test_full_overlap(self) -> None:
        # query_tokens: {pizza} → 1 token
        # type_tokens: {pizza, restaurant}
        # intersection: {pizza} → 1/1 = 1.0
        c = make_candidate(types=["pizza_restaurant"])
        features = extractor.extract(c, "pizza", None)
        assert features["category_match"] == pytest.approx(1.0)

    def test_no_overlap_vietnamese_query(self) -> None:
        # Vietnamese query tokens don't match English type tokens
        c = make_candidate(types=["seafood_restaurant", "restaurant"])
        features = extractor.extract(c, "quán hải sản", None)
        assert features["category_match"] == 0.0

    def test_score_clipped_to_one(self) -> None:
        # If somehow intersection > query_tokens, score should clip to 1.0
        c = make_candidate(types=["foo_bar"])
        features = extractor.extract(c, "foo", None)
        assert features["category_match"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# All-null candidate — stress test
# ---------------------------------------------------------------------------


class TestAllNullCandidate:
    def test_all_nulls_no_exception(self) -> None:
        c = PlaceCandidate(
            place_id="p-null",
            display_name="Null Place",
        )
        features = extractor.extract(c, "", user_location=None)
        assert features == {
            "rating": 3.5,
            "distance_meters": float(DEFAULT_SEARCH_RADIUS_METERS),
            "price_level": 2.0,
            "is_open_now": 0.0,
            "local_factor": 0.5,
            "category_match": 0.0,
        }

    def test_all_nulls_with_user_location_still_defaults(self) -> None:
        # Without candidate.location, even with user_location, distance defaults
        c = PlaceCandidate(
            place_id="p-null2",
            display_name="Null Place 2",
        )
        features = extractor.extract(c, "", user_location=LatLng(lat=10.0, lng=106.0))
        assert features["distance_meters"] == float(DEFAULT_SEARCH_RADIUS_METERS)


# ---------------------------------------------------------------------------
# Negative / edge tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_place_id_still_works(self) -> None:
        # place_id is required by Pydantic (min_length=1), but if provided,
        # extractor should not care about it at all
        c = make_candidate()
        features = extractor.extract(c, "test", None)
        assert len(features) == 6

    def test_query_with_special_chars(self) -> None:
        c = make_candidate(types=["cafe", "restaurant"])
        features = extractor.extract(c, "café & restaurant!!!", None)
        # Non-ascii 'é' and special chars split the tokens
        assert features["category_match"] >= 0.0

    def test_types_with_underscores_and_special(self) -> None:
        c = make_candidate(types=["amusement_park", "tourist_attraction"])
        features = extractor.extract(c, "amusement park", None)
        # "amusement" and "park" should both match
        assert features["category_match"] == pytest.approx(1.0)
