"""Field mask audit test — R009 verification.

Ensures Google Places field masks are comprehensive and that the
X-Goog-FieldMask header is present on all Google Places API endpoints.

Audits:
1. Every field consumed by normalize_place() is covered by the field masks.
2. Documents any mask fields not yet consumed (reserved for future use).
3. X-Goog-FieldMask header is set in _auth_headers().
4. All three endpoints (text_search, nearby_search, details) propagate the header.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.models.places import (
    GOOGLE_PLACE_DETAILS_FIELD_MASK,
    GOOGLE_PLACES_FIELD_MASK,
)
from agents.tools.places_service import GooglePlacesService, normalize_place


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_field_mask(mask: str, *, strip_prefix: str | None = None) -> set[str]:
    """Parse a comma-separated field mask into a set of camelCase field names.

    Optionally strips a common prefix (e.g. "places.") from each field.
    """
    fields = set()
    for part in mask.split(","):
        field = part.strip()
        if not field:
            continue
        if strip_prefix and field.startswith(strip_prefix):
            field = field[len(strip_prefix):]
        fields.add(field)
    return fields


def _extract_consumed_fields() -> set[str]:
    """Extract all field names read via place.get() from normalize_place source.

    Scans the source code of normalize_place for patterns like
    place.get("fieldName") or place.get("fieldName", default).
    This captures fields consumed directly and via helper function calls
    that receive the `place` dict.
    """
    source = inspect.getsource(normalize_place)
    return set(re.findall(r'place\.get\(\s*"(\w+)"', source))


def _extract_helper_consumed_fields() -> set[str]:
    """Extract field names consumed by helper functions called from normalize_place.

    Specifically scans _open_now_google which reads from the place dict
    but is called as a function rather than inline.
    """
    from agents.tools.places_service import _open_now_google
    source = inspect.getsource(_open_now_google)
    return set(re.findall(r'place\.get\(\s*"(\w+)"', source))


# ---------------------------------------------------------------------------
# Fixture: parsed masks and consumed fields
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def search_mask_fields() -> set[str]:
    """Fields from GOOGLE_PLACES_FIELD_MASK (search), prefix-stripped."""
    return _parse_field_mask(GOOGLE_PLACES_FIELD_MASK, strip_prefix="places.")


@pytest.fixture(scope="module")
def details_mask_fields() -> set[str]:
    """Fields from GOOGLE_PLACE_DETAILS_FIELD_MASK (details), no prefix."""
    return _parse_field_mask(GOOGLE_PLACE_DETAILS_FIELD_MASK)


@pytest.fixture(scope="module")
def consumed_fields() -> set[str]:
    """All field names consumed by normalize_place() and its helpers."""
    fields = _extract_consumed_fields()
    fields |= _extract_helper_consumed_fields()
    return fields


@pytest.fixture(scope="module")
def all_mask_fields() -> set[str]:
    """Union of search and details mask fields."""
    return (
        _parse_field_mask(GOOGLE_PLACES_FIELD_MASK, strip_prefix="places.")
        | _parse_field_mask(GOOGLE_PLACE_DETAILS_FIELD_MASK)
    )


# ---------------------------------------------------------------------------
# 1. Field mask completeness — consumed fields must be in masks
# ---------------------------------------------------------------------------

class TestFieldMaskCompleteness:
    """Every field consumed by normalize_place() must be in a field mask."""

    def test_search_mask_fields_consumed_by_normalize(
        self, search_mask_fields: set[str], consumed_fields: set[str]
    ) -> None:
        """Every field in GOOGLE_PLACES_FIELD_MASK is consumed or documented as reserved."""
        # Fields in the search mask that are not directly consumed by normalize_place
        # but are intentionally included for future use or completeness.
        reserved_fields: set[str] = set()

        unconsumed = search_mask_fields - consumed_fields - reserved_fields
        assert not unconsumed, (
            f"GOOGLE_PLACES_FIELD_MASK fields not consumed by normalize_place(): "
            f"{sorted(unconsumed)}. Either consume them or add to reserved_fields."
        )

    def test_details_mask_consumed_or_documented(
        self, details_mask_fields: set[str], consumed_fields: set[str]
    ) -> None:
        """Every field in GOOGLE_PLACE_DETAILS_FIELD_MASK is consumed or documented as reserved."""
        # These fields are in the mask for API completeness but not yet
        # consumed by normalize_place(). They are fetched so future
        # normalization can use them without a mask update.
        reserved_fields = {
            "currentSecondaryOpeningHours",
            "regularSecondaryOpeningHours",
        }

        unconsumed = details_mask_fields - consumed_fields - reserved_fields
        assert not unconsumed, (
            f"GOOGLE_PLACE_DETAILS_FIELD_MASK fields not consumed by normalize_place() "
            f"and not documented as reserved: {sorted(unconsumed)}"
        )

    def test_consumed_fields_covered_by_masks(
        self, consumed_fields: set[str], all_mask_fields: set[str]
    ) -> None:
        """Every field consumed by normalize_place() must be in at least one mask.

        This ensures no field is silently missing from the API response
        because the mask didn't request it.
        """
        missing_from_masks = consumed_fields - all_mask_fields
        assert not missing_from_masks, (
            f"Fields consumed by normalize_place() but missing from both field masks: "
            f"{sorted(missing_from_masks)}. Add them to the appropriate mask."
        )


# ---------------------------------------------------------------------------
# 2. X-Goog-FieldMask header presence
# ---------------------------------------------------------------------------

class TestXGoogFieldMaskHeader:
    """Verify X-Goog-FieldMask header is correctly set."""

    @staticmethod
    def _make_service() -> GooglePlacesService:
        """Create a GooglePlacesService with mocked settings for header inspection."""
        svc = GooglePlacesService.__new__(GooglePlacesService)
        mock_settings = MagicMock()
        mock_settings.GOOGLE_PLACES_API_KEY = "test-key-audit"
        svc._settings = mock_settings
        return svc

    def test_auth_headers_contains_field_mask_key(self) -> None:
        """_auth_headers() must include the X-Goog-FieldMask header."""
        svc = self._make_service()
        headers = svc._auth_headers()
        assert "X-Goog-FieldMask" in headers, (
            "X-Goog-FieldMask header is missing from _auth_headers()"
        )

    def test_auth_headers_default_field_mask_value(self) -> None:
        """Default field mask in _auth_headers() must match GOOGLE_PLACES_FIELD_MASK."""
        svc = self._make_service()
        headers = svc._auth_headers()
        assert headers["X-Goog-FieldMask"] == GOOGLE_PLACES_FIELD_MASK

    def test_auth_headers_custom_field_mask(self) -> None:
        """_auth_headers() must propagate a custom field_mask argument."""
        svc = self._make_service()
        custom_mask = "places.id,places.displayName"
        headers = svc._auth_headers(field_mask=custom_mask)
        assert headers["X-Goog-FieldMask"] == custom_mask

    def test_auth_headers_details_field_mask(self) -> None:
        """Details endpoint must use GOOGLE_PLACE_DETAILS_FIELD_MASK."""
        svc = self._make_service()
        headers = svc._auth_headers(field_mask=GOOGLE_PLACE_DETAILS_FIELD_MASK)
        assert headers["X-Goog-FieldMask"] == GOOGLE_PLACE_DETAILS_FIELD_MASK


# ---------------------------------------------------------------------------
# 3. Endpoint → _auth_headers propagation
# ---------------------------------------------------------------------------

class TestEndpointFieldMaskPropagation:
    """All three endpoints must call _auth_headers() with appropriate field masks."""

    def test_text_search_uses_auth_headers(self) -> None:
        """text_search() source must call _auth_headers and reference the search mask."""
        source = inspect.getsource(GooglePlacesService.text_search)
        # text_search delegates to _execute_search which calls _auth_headers
        exec_source = inspect.getsource(GooglePlacesService._execute_search)
        assert "_auth_headers" in exec_source, (
            "text_search path does not call _auth_headers()"
        )
        # Verify the search field mask is referenced in the text_search metadata
        assert "GOOGLE_PLACES_FIELD_MASK" in source, (
            "text_search() does not reference GOOGLE_PLACES_FIELD_MASK in metadata"
        )

    def test_nearby_search_uses_auth_headers(self) -> None:
        """nearby_search() source must call _auth_headers and reference the search mask."""
        source = inspect.getsource(GooglePlacesService.nearby_search)
        exec_source = inspect.getsource(GooglePlacesService._execute_search)
        assert "_auth_headers" in exec_source, (
            "nearby_search path does not call _auth_headers()"
        )
        assert "GOOGLE_PLACES_FIELD_MASK" in source, (
            "nearby_search() does not reference GOOGLE_PLACES_FIELD_MASK in metadata"
        )

    def test_details_uses_auth_headers_with_details_mask(self) -> None:
        """details() must call _auth_headers with GOOGLE_PLACE_DETAILS_FIELD_MASK."""
        source = inspect.getsource(GooglePlacesService.details)
        assert "_auth_headers" in source, (
            "details() does not call _auth_headers()"
        )
        assert "GOOGLE_PLACE_DETAILS_FIELD_MASK" in source, (
            "details() does not pass GOOGLE_PLACE_DETAILS_FIELD_MASK to _auth_headers()"
        )


# ---------------------------------------------------------------------------
# 4. Field mask format validation
# ---------------------------------------------------------------------------

class TestFieldMaskFormat:
    """Field masks must follow Google Places API (New) conventions."""

    def test_search_mask_uses_places_prefix(self) -> None:
        """All search mask fields must be prefixed with 'places.'."""
        for field in GOOGLE_PLACES_FIELD_MASK.split(","):
            field = field.strip()
            assert field.startswith("places."), (
                f"Search mask field missing 'places.' prefix: {field}"
            )

    def test_details_mask_no_places_prefix(self) -> None:
        """Details mask fields must NOT have 'places.' prefix (single-resource response)."""
        for field in GOOGLE_PLACE_DETAILS_FIELD_MASK.split(","):
            field = field.strip()
            assert not field.startswith("places."), (
                f"Details mask field should not have 'places.' prefix: {field}"
            )

    def test_no_empty_fields(self) -> None:
        """Neither mask should contain empty field entries."""
        for field in GOOGLE_PLACES_FIELD_MASK.split(","):
            assert field.strip(), "GOOGLE_PLACES_FIELD_MASK contains an empty field entry"
        for field in GOOGLE_PLACE_DETAILS_FIELD_MASK.split(","):
            assert field.strip(), "GOOGLE_PLACE_DETAILS_FIELD_MASK contains an empty field entry"
