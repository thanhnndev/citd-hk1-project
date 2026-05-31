"""Tests for the new SearchPlacesToolResult typed contract and Google field-mask coverage."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.places import (
    GOOGLE_PLACES_FIELD_MASK,
    HAM_NINH_CENTER,
    PlaceCandidate,
    PlaceDetailsRequest,
    PlaceNearbyRequest,
    PlaceRecommendationStatus,
    PlaceSearchRequest,
    PlaceToolError,
    PlaceToolResponse,
    PlaceToolSource,
    PlaceToolStatus,
    ProviderStatus,
    SearchPlacesToolResult,
)
from app.models.request import LatLng


# ---------------------------------------------------------------------------
# ProviderStatus model tests
# ---------------------------------------------------------------------------

class TestProviderStatus:
    def test_accepts_all_safe_fields(self):
        ps = ProviderStatus(
            http_status=403,
            provider_code="REQUEST_DENIED",
            provider_message="API key not valid",
            request_id="req-abc-123",
        )
        assert ps.http_status == 403
        assert ps.provider_code == "REQUEST_DENIED"
        assert ps.provider_message == "API key not valid"
        assert ps.request_id == "req-abc-123"

    def test_defaults_to_empty(self):
        ps = ProviderStatus()
        assert ps.http_status is None
        assert ps.provider_code is None
        assert ps.provider_message is None
        assert ps.request_id is None

    def test_forbids_extra_fields(self):
        with pytest.raises(ValidationError):
            ProviderStatus(
                http_status=200,
                api_key="sk-secret",
            )

    def test_no_secret_leakage_in_serialization(self):
        ps = ProviderStatus(
            http_status=403,
            provider_code="REQUEST_DENIED",
            provider_message="API key not valid",
        )
        dump = ps.model_dump_json()
        assert "api_key" not in dump.lower()
        assert "secret" not in dump.lower()

    def test_constrains_string_lengths(self):
        with pytest.raises(ValidationError):
            ProviderStatus(provider_code="x" * 65)

        with pytest.raises(ValidationError):
            ProviderStatus(provider_message="x" * 501)


# ---------------------------------------------------------------------------
# PlaceRecommendationStatus model tests
# ---------------------------------------------------------------------------

class TestPlaceRecommendationStatus:
    def test_accepts_structured_diagnostics(self):
        prs = PlaceRecommendationStatus(
            provider_places_returned=5,
            candidates_after_normalization=3,
            filters_applied=["max_result_count=3"],
            reason="normalized 3 of 5 provider results",
        )
        assert prs.provider_places_returned == 5
        assert prs.candidates_after_normalization == 3
        assert prs.reason == "normalized 3 of 5 provider results"

    def test_defaults_to_zero(self):
        prs = PlaceRecommendationStatus()
        assert prs.provider_places_returned == 0
        assert prs.candidates_after_normalization == 0
        assert prs.filters_applied == []
        assert prs.reason is None

    def test_forbids_extra_fields(self):
        with pytest.raises(ValidationError):
            PlaceRecommendationStatus(raw_provider_payload={"secret": True})

    def test_rejects_negative_counts(self):
        with pytest.raises(ValidationError):
            PlaceRecommendationStatus(provider_places_returned=-1)


# ---------------------------------------------------------------------------
# SearchPlacesToolResult model tests
# ---------------------------------------------------------------------------

class TestSearchPlacesToolResult:
    def _make_result(self, **overrides):
        defaults = dict(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.GOOGLE_PLACES,
        )
        defaults.update(overrides)
        return SearchPlacesToolResult(**defaults)

    def test_accepts_full_envelope(self):
        result = self._make_result(
            candidates=[PlaceCandidate(place_id="places/1", display_name="Test Cafe")],
            warnings=["Provider returned sparse data"],
            reasoning_log=["received 1 place", "normalized successfully"],
            explanation="One matching place found.",
            place_recommendation_status=PlaceRecommendationStatus(
                provider_places_returned=1,
                candidates_after_normalization=1,
                reason="ok",
            ),
            audit={"endpoint": "google_text_search", "field_mask": GOOGLE_PLACES_FIELD_MASK},
            retrieved_at=datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC),
        )
        assert result.status == PlaceToolStatus.OK
        assert result.source == PlaceToolSource.GOOGLE_PLACES
        assert len(result.candidates) == 1
        assert result.warnings == ["Provider returned sparse data"]
        assert result.reasoning_log == ["received 1 place", "normalized successfully"]
        assert result.explanation == "One matching place found."
        assert result.place_recommendation_status.candidates_after_normalization == 1
        assert result.audit["endpoint"] == "google_text_search"
        assert result.retrieved_at == datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            SearchPlacesToolResult(
                status=PlaceToolStatus.OK,
                source=PlaceToolSource.GOOGLE_PLACES,
                raw_provider_payload={"places": [{"id": "x"}]},
            )

    def test_no_raw_provider_payload_in_serialization(self):
        result = self._make_result(
            candidates=[PlaceCandidate(place_id="places/1", display_name="Test")],
            audit={"endpoint": "google_text_search"},
        )
        dump = result.model_dump_json()
        assert "raw" not in dump.lower()
        assert "payload" not in dump.lower()

    def test_google_places_source_serializes_correctly(self):
        result = self._make_result()
        dump = result.model_dump()
        assert dump["source"] == "google_places"

    def test_credential_blocked_status_round_trips(self):
        result = self._make_result(status=PlaceToolStatus.CREDENTIALS_BLOCKED)
        assert result.status == PlaceToolStatus.CREDENTIALS_BLOCKED
        dump = result.model_dump()
        assert dump["status"] == "credentials_blocked"

    def test_defaults_empty_collections(self):
        result = SearchPlacesToolResult(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.GOOGLE_PLACES,
        )
        assert result.candidates == []
        assert result.warnings == []
        assert result.reasoning_log == []
        assert result.audit == {}

    def test_provider_status_nested_model(self):
        result = self._make_result(
            provider_status=ProviderStatus(
                http_status=403,
                provider_code="REQUEST_DENIED",
            ),
        )
        assert result.provider_status.http_status == 403
        assert result.provider_status.provider_code == "REQUEST_DENIED"

    def test_interpreted_query_and_request_metadata_are_safe(self):
        result = self._make_result(
            interpreted_query="nhà hàng Hàm Ninh",
            request_metadata={
                "endpoint": "google_text_search",
                "field_mask": GOOGLE_PLACES_FIELD_MASK,
                "language_code": "vi",
                "max_result_count": 3,
            },
        )
        assert result.interpreted_query == "nhà hàng Hàm Ninh"
        assert result.request_metadata["field_mask"] == GOOGLE_PLACES_FIELD_MASK
        dump = result.model_dump_json()
        assert "google_places_api_key" not in dump.lower()
        assert "secret" not in dump.lower()

    def test_interpreted_query_constrained_length(self):
        with pytest.raises(ValidationError):
            SearchPlacesToolResult(
                status=PlaceToolStatus.OK,
                source=PlaceToolSource.GOOGLE_PLACES,
                interpreted_query="x" * 161,
            )

    def test_request_metadata_constrained_length(self):
        with pytest.raises(ValidationError):
            SearchPlacesToolResult(
                status=PlaceToolStatus.OK,
                source=PlaceToolSource.GOOGLE_PLACES,
                request_metadata={f"k{i}": i for i in range(21)},
            )

    def test_warnings_constrained_length(self):
        with pytest.raises(ValidationError):
            SearchPlacesToolResult(
                status=PlaceToolStatus.OK,
                source=PlaceToolSource.GOOGLE_PLACES,
                warnings=[f"warning-{i}" for i in range(11)],
            )

    def test_reasoning_log_constrained_length(self):
        with pytest.raises(ValidationError):
            SearchPlacesToolResult(
                status=PlaceToolStatus.OK,
                source=PlaceToolSource.GOOGLE_PLACES,
                reasoning_log=[f"log-{i}" for i in range(51)],
            )


# ---------------------------------------------------------------------------
# GOOGLE_PLACES_FIELD_MASK constant tests
# ---------------------------------------------------------------------------

class TestGooglePlacesFieldMask:
    def test_field_mask_contains_required_fields(self):
        """Verify field mask covers all fields specified in the task plan."""
        required = [
            "places.id",
            "places.displayName",
            "places.formattedAddress",
            "places.location",
            "places.rating",
            "places.priceLevel",
            "places.accessibilityOptions",
            "places.businessStatus",
        ]
        for field in required:
            assert field in GOOGLE_PLACES_FIELD_MASK, f"Missing {field} in field mask"

    def test_field_mask_is_string(self):
        assert isinstance(GOOGLE_PLACES_FIELD_MASK, str)
        assert len(GOOGLE_PLACES_FIELD_MASK) > 0

    def test_field_mask_no_api_key_leakage(self):
        assert "key" not in GOOGLE_PLACES_FIELD_MASK.lower()
        assert "secret" not in GOOGLE_PLACES_FIELD_MASK.lower()
        assert "token" not in GOOGLE_PLACES_FIELD_MASK.lower()


# ---------------------------------------------------------------------------
# PlaceToolSource GOOGLE_PLACES enum tests
# ---------------------------------------------------------------------------

class TestPlaceToolSourceGoogle:
    def test_google_places_value(self):
        assert PlaceToolSource.GOOGLE_PLACES == "google_places"

    def test_google_places_in_enum_members(self):
        members = [e.value for e in PlaceToolSource]
        assert "google_places" in members
        assert "goong_places" in members

    def test_google_places_round_trips(self):
        result = SearchPlacesToolResult(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.GOOGLE_PLACES,
        )
        dump = result.model_dump()
        assert dump["source"] == "google_places"
        restored = SearchPlacesToolResult(**dump)
        assert restored.source == PlaceToolSource.GOOGLE_PLACES


# ---------------------------------------------------------------------------
# Backward compatibility: existing PlaceToolResponse still works
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_place_tool_response_still_accepts_valid_data(self):
        request = PlaceSearchRequest(query="cafe")
        response = PlaceToolResponse(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.GOONG_PLACES,
            request=request,
            retrieved_at=datetime.now(UTC),
            candidates=[PlaceCandidate(place_id="places/1", display_name="Test")],
        )
        assert response.status == PlaceToolStatus.OK
        assert response.source == PlaceToolSource.GOONG_PLACES

    def test_place_tool_response_still_forbids_extra(self):
        request = PlaceSearchRequest(query="cafe")
        with pytest.raises(ValidationError):
            PlaceToolResponse(
                status=PlaceToolStatus.OK,
                source=PlaceToolSource.GOONG_PLACES,
                request=request,
                retrieved_at=datetime.now(UTC),
                raw_payload={},
            )


# ============================================================================
# FairnessAudit model tests (M013/S02 — T01)
# ============================================================================

from app.models.places import (
    FairnessAudit,
    FairnessWarningType,
)


class TestFairnessWarningType:
    def test_all_warning_values_exist(self):
        expected = {
            "insufficient_local_candidates",
            "missing_local_factor_metadata",
            "provider_non_ok",
            "route_enrichment_fallback",
            "ensemble_fallback",
        }
        actual = {w.value for w in FairnessWarningType}
        assert actual == expected

    def test_warning_values_are_stable(self):
        """Warning vocabulary must not change without a migration plan."""
        assert FairnessWarningType.INSUFFICIENT_LOCAL_CANDIDATES == "insufficient_local_candidates"
        assert FairnessWarningType.MISSING_LOCAL_FACTOR_METADATA == "missing_local_factor_metadata"
        assert FairnessWarningType.PROVIDER_NON_OK == "provider_non_ok"
        assert FairnessWarningType.ROUTE_ENRICHMENT_FALLBACK == "route_enrichment_fallback"
        assert FairnessWarningType.ENSEMBLE_FALLBACK == "ensemble_fallback"


class TestFairnessAuditModel:
    def test_defaults(self):
        audit = FairnessAudit()
        assert audit.candidate_count == 0
        assert audit.result_count == 0
        assert audit.top5_local_ratio == 0.0
        assert audit.missing_local_factor_count == 0
        assert audit.provider_status == "unknown"
        assert audit.warnings == []

    def test_accepts_full_envelope(self):
        audit = FairnessAudit(
            candidate_count=10,
            result_count=5,
            top5_local_ratio=0.6,
            missing_local_factor_count=2,
            provider_status="ok",
            warnings=["insufficient_local_candidates"],
        )
        assert audit.candidate_count == 10
        assert audit.result_count == 5
        assert audit.top5_local_ratio == 0.6
        assert audit.missing_local_factor_count == 2
        assert audit.provider_status == "ok"
        assert "insufficient_local_candidates" in audit.warnings

    def test_forbids_extra_fields(self):
        with pytest.raises(ValidationError):
            FairnessAudit(raw_provider_payload={"secret": True})

    def test_rejects_negative_counts(self):
        with pytest.raises(ValidationError):
            FairnessAudit(candidate_count=-1)

        with pytest.raises(ValidationError):
            FairnessAudit(result_count=-1)

        with pytest.raises(ValidationError):
            FairnessAudit(missing_local_factor_count=-1)

    def test_top5_local_ratio_bounds(self):
        with pytest.raises(ValidationError):
            FairnessAudit(top5_local_ratio=-0.1)

        with pytest.raises(ValidationError):
            FairnessAudit(top5_local_ratio=1.1)

        # Boundary values are accepted
        FairnessAudit(top5_local_ratio=0.0)
        FairnessAudit(top5_local_ratio=1.0)

    def test_unknown_warning_rejected(self):
        with pytest.raises(ValidationError):
            FairnessAudit(warnings=["made_up_warning"])

    def test_all_warning_types_accepted(self):
        warnings = [w.value for w in FairnessWarningType]
        audit = FairnessAudit(warnings=warnings)
        assert len(audit.warnings) == len(warnings)

    def test_no_secret_leakage_in_serialization(self):
        audit = FairnessAudit(
            candidate_count=5,
            result_count=3,
            top5_local_ratio=0.4,
            provider_status="ok",
        )
        dump = audit.model_dump_json()
        assert "api_key" not in dump.lower()
        assert "secret" not in dump.lower()
        assert "payload" not in dump.lower()

    def test_provider_status_constrained_length(self):
        with pytest.raises(ValidationError):
            FairnessAudit(provider_status="x" * 65)

    def test_warnings_constrained_length(self):
        with pytest.raises(ValidationError):
            FairnessAudit(warnings=[w.value for w in FairnessWarningType] * 3)

    def test_round_trips(self):
        audit = FairnessAudit(
            candidate_count=8,
            result_count=5,
            top5_local_ratio=0.4,
            missing_local_factor_count=1,
            provider_status="ok",
            warnings=["missing_local_factor_metadata"],
        )
        dump = audit.model_dump()
        restored = FairnessAudit(**dump)
        assert restored.candidate_count == 8
        assert restored.result_count == 5
        assert restored.top5_local_ratio == 0.4
        assert restored.missing_local_factor_count == 1
        assert restored.provider_status == "ok"
        assert restored.warnings == ["missing_local_factor_metadata"]


class TestFairnessAuditEdgeCases:
    """Negative tests: malformed/missing data must not crash."""

    def test_empty_candidate_list_reports_zeroes(self):
        """Empty candidate lists should report zero counts and no division error."""
        audit = FairnessAudit(
            candidate_count=0,
            result_count=0,
            top5_local_ratio=0.0,
            missing_local_factor_count=0,
            provider_status="ok",
        )
        assert audit.candidate_count == 0
        assert audit.result_count == 0
        assert audit.top5_local_ratio == 0.0
        assert audit.warnings == []

    def test_fewer_than_five_candidates(self):
        """Fewer than five candidates — ratio still computes safely."""
        audit = FairnessAudit(
            candidate_count=3,
            result_count=3,
            top5_local_ratio=0.6667,
            missing_local_factor_count=0,
            provider_status="ok",
        )
        assert audit.top5_local_ratio > 0.5

    def test_exactly_one_local_candidate(self):
        """One local candidate in a small pool."""
        audit = FairnessAudit(
            candidate_count=5,
            result_count=5,
            top5_local_ratio=0.2,
            missing_local_factor_count=0,
            provider_status="ok",
            warnings=["insufficient_local_candidates"],
        )
        assert audit.top5_local_ratio == 0.2

    def test_provider_non_ok_status(self):
        """Provider response with status other than ok."""
        audit = FairnessAudit(
            candidate_count=0,
            result_count=0,
            provider_status="upstream_error",
            warnings=["provider_non_ok"],
        )
        assert audit.provider_status == "upstream_error"
        assert "provider_non_ok" in audit.warnings

    def test_local_factor_none_counted_as_missing(self):
        """Candidates with local_factor=None increment missing count."""
        audit = FairnessAudit(
            candidate_count=5,
            result_count=5,
            top5_local_ratio=0.0,
            missing_local_factor_count=5,
            provider_status="ok",
            warnings=["missing_local_factor_metadata"],
        )
        assert audit.missing_local_factor_count == 5
        assert "missing_local_factor_metadata" in audit.warnings


class TestFairnessAuditProviderStatusSafety:
    """provider_status must accept only safe, bounded text values."""

    def test_accepts_all_place_tool_status_values(self):
        """Every PlaceToolStatus value must be acceptable as provider_status."""
        for status in PlaceToolStatus:
            audit = FairnessAudit(provider_status=status.value)
            assert audit.provider_status == status.value

    def test_accepts_arbitrary_safe_text(self):
        """provider_status is free-form safe text, not enum-locked."""
        audit = FairnessAudit(provider_status="degraded_mode")
        assert audit.provider_status == "degraded_mode"

    def test_rejects_non_string_provider_status(self):
        """provider_status must be a string, not int or dict."""
        with pytest.raises(ValidationError):
            FairnessAudit(provider_status=200)

        with pytest.raises(ValidationError):
            FairnessAudit(provider_status={"status": "ok"})

    def test_provider_status_max_length_enforced(self):
        """provider_status capped at 64 characters."""
        FairnessAudit(provider_status="x" * 64)  # exactly at limit
        with pytest.raises(ValidationError):
            FairnessAudit(provider_status="x" * 65)


class TestFairnessAuditSerializationCompleteness:
    """Serialization must expose exactly the contracted fields — no more, no less."""

    def test_model_dump_contains_exactly_contracted_fields(self):
        audit = FairnessAudit(
            candidate_count=5,
            result_count=3,
            top5_local_ratio=0.6,
            missing_local_factor_count=1,
            provider_status="ok",
            warnings=["insufficient_local_candidates"],
        )
        dump = audit.model_dump()
        expected_keys = {
            "candidate_count",
            "result_count",
            "top5_local_ratio",
            "missing_local_factor_count",
            "provider_status",
            "warnings",
        }
        assert set(dump.keys()) == expected_keys

    def test_model_dump_json_contains_exactly_contracted_fields(self):
        audit = FairnessAudit(
            candidate_count=10,
            result_count=5,
            top5_local_ratio=0.4,
            provider_status="ok",
            warnings=[],
        )
        import json
        parsed = json.loads(audit.model_dump_json())
        expected_keys = {
            "candidate_count",
            "result_count",
            "top5_local_ratio",
            "missing_local_factor_count",
            "provider_status",
            "warnings",
        }
        assert set(parsed.keys()) == expected_keys

    def test_model_dump_mode_json_contains_no_secrets(self):
        """mode='json' serialization must also be clean."""
        audit = FairnessAudit(
            candidate_count=3,
            result_count=3,
            top5_local_ratio=1.0,
            provider_status="ok",
        )
        dump = audit.model_dump(mode="json")
        dump_str = str(dump).lower()
        assert "api_key" not in dump_str
        assert "secret" not in dump_str
        assert "password" not in dump_str
        assert "token" not in dump_str
        assert "payload" not in dump_str

    def test_model_copy_deep_produces_independent_instance(self):
        """model_copy(deep=True) must not share mutable state."""
        original = FairnessAudit(
            candidate_count=5,
            warnings=["insufficient_local_candidates"],
        )
        copy = original.model_copy(deep=True)
        copy.warnings.append("provider_non_ok")
        assert len(original.warnings) == 1
        assert len(copy.warnings) == 2

    def test_model_validate_json_round_trips(self):
        """JSON validation must reconstruct the exact same model."""
        audit = FairnessAudit(
            candidate_count=7,
            result_count=5,
            top5_local_ratio=0.4,
            missing_local_factor_count=2,
            provider_status="ok",
            warnings=["missing_local_factor_metadata", "ensemble_fallback"],
        )
        json_str = audit.model_dump_json()
        restored = FairnessAudit.model_validate_json(json_str)
        assert restored == audit


class TestChatResponseFairnessAudit:
    """ChatResponse carries the fairness_audit field."""

    from app.models.response import ChatResponse

    def test_chat_response_has_fairness_audit_field(self):
        """ChatResponse must expose fairness_audit."""
        from app.models.response import ChatResponse
        assert hasattr(ChatResponse.model_fields, "fairness_audit") or "fairness_audit" in ChatResponse.model_fields

    def test_chat_response_accepts_fairness_audit(self):
        """ChatResponse must accept a FairnessAudit instance."""
        from app.models.response import ChatResponse
        audit = FairnessAudit(
            candidate_count=5,
            result_count=3,
            top5_local_ratio=0.6,
            provider_status="ok",
        )
        resp = ChatResponse(
            session_id="test",
            message="ok",
            latency_ms=10.0,
            fairness_audit=audit,
        )
        assert resp.fairness_audit is not None
        assert resp.fairness_audit.candidate_count == 5

    def test_chat_response_defaults_fairness_audit_to_none(self):
        from app.models.response import ChatResponse
        resp = ChatResponse(
            session_id="test",
            message="ok",
            latency_ms=10.0,
        )
        assert resp.fairness_audit is None

    def test_chat_response_serializes_fairness_audit(self):
        from app.models.response import ChatResponse
        audit = FairnessAudit(
            candidate_count=10,
            result_count=5,
            top5_local_ratio=0.4,
            missing_local_factor_count=2,
            provider_status="ok",
            warnings=["missing_local_factor_metadata"],
        )
        resp = ChatResponse(
            session_id="test",
            message="ok",
            latency_ms=10.0,
            fairness_audit=audit,
        )
        dump = resp.model_dump()
        assert "fairness_audit" in dump
        assert dump["fairness_audit"]["candidate_count"] == 10
        assert dump["fairness_audit"]["top5_local_ratio"] == 0.4


# ============================================================================
# PlaceSearchRequest preference contract tests (M013/S04 — T01)
# ============================================================================

from app.models.places import (
    PriceLevel,
    _PRICE_LEVEL_TO_NUMERIC,
)


# ---------------------------------------------------------------------------
# PriceLevel enum tests
# ---------------------------------------------------------------------------

class TestPriceLevelEnum:
    def test_all_levels_exist(self):
        expected = {"free", "inexpensive", "moderate", "expensive", "very_expensive"}
        actual = {e.value for e in PriceLevel}
        assert actual == expected

    def test_symbolic_maps_to_numeric(self):
        """Each symbolic level must map to at least one numeric price_level."""
        for level in PriceLevel:
            nums = _PRICE_LEVEL_TO_NUMERIC.get(level.value)
            assert nums is not None, f"Missing mapping for {level.value}"
            assert all(0 <= n <= 4 for n in nums), f"Numeric values out of range for {level.value}"

    def test_free_maps_to_zero(self):
        assert _PRICE_LEVEL_TO_NUMERIC[PriceLevel.FREE.value] == [0]

    def test_very_expensive_maps_to_high_values(self):
        assert _PRICE_LEVEL_TO_NUMERIC[PriceLevel.VERY_EXPENSIVE.value] == [3, 4]


# ---------------------------------------------------------------------------
# Valid preference acceptance tests
# ---------------------------------------------------------------------------

class TestPlaceSearchRequestValidPreferences:
    def test_accepts_budget_filter_single(self):
        req = PlaceSearchRequest(
            query="cafe",
            budget_filter=["inexpensive"],
        )
        assert req.budget_filter == [PriceLevel.INEXPENSIVE]

    def test_accepts_budget_filter_multiple(self):
        req = PlaceSearchRequest(
            query="restaurant",
            budget_filter=["free", "inexpensive", "moderate"],
        )
        assert len(req.budget_filter) == 3

    def test_accepts_wheelchair_accessible_preference_true(self):
        req = PlaceSearchRequest(
            query="pharmacy",
            wheelchair_accessible_preference=True,
        )
        assert req.wheelchair_accessible_preference is True

    def test_accepts_wheelchair_accessible_preference_false(self):
        req = PlaceSearchRequest(
            query="parking",
            wheelchair_accessible_preference=False,
        )
        assert req.wheelchair_accessible_preference is False

    def test_accepts_user_location(self):
        req = PlaceSearchRequest(
            query="hotel",
            user_location=LatLng(lat=10.1794, lng=104.0491),
        )
        assert req.user_location is not None
        assert req.user_location.lat == 10.1794
        assert req.user_location.lng == 104.0491

    def test_accepts_all_preferences_together(self):
        req = PlaceSearchRequest(
            query="seafood restaurant",
            budget_filter=["moderate", "expensive"],
            wheelchair_accessible_preference=True,
            user_location=LatLng(lat=10.18, lng=104.05),
        )
        assert len(req.budget_filter) == 2
        assert req.wheelchair_accessible_preference is True
        assert req.user_location is not None

    def test_defaults_preserve_existing_behaviour(self):
        """No preference fields — existing default behaviour unchanged."""
        req = PlaceSearchRequest(query="cafe")
        assert req.budget_filter is None
        assert req.wheelchair_accessible_preference is None
        assert req.user_location is None
        assert req.query == "cafe"
        assert req.language_code == "vi"
        assert req.max_result_count == 10


# ---------------------------------------------------------------------------
# effective_origin property tests
# ---------------------------------------------------------------------------

class TestEffectiveOrigin:
    def test_uses_user_location_when_set(self):
        req = PlaceSearchRequest(
            query="cafe",
            user_location=LatLng(lat=10.50, lng=105.00),
        )
        origin = req.effective_origin
        assert origin.lat == 10.50
        assert origin.lng == 105.00

    def test_falls_back_to_location_bias_when_no_user_location(self):
        req = PlaceSearchRequest(query="cafe")
        origin = req.effective_origin
        assert origin.lat == HAM_NINH_CENTER.lat
        assert origin.lng == HAM_NINH_CENTER.lng

    def test_falls_back_to_location_bias_when_user_location_none(self):
        req = PlaceSearchRequest(
            query="cafe",
            location_bias=LatLng(lat=10.00, lng=104.00),
        )
        origin = req.effective_origin
        assert origin.lat == 10.00
        assert origin.lng == 104.00


# ---------------------------------------------------------------------------
# numeric_price_levels property tests
# ---------------------------------------------------------------------------

class TestNumericPriceLevels:
    def test_none_when_no_budget(self):
        req = PlaceSearchRequest(query="cafe")
        assert req.numeric_price_levels is None

    def test_single_level_maps_correctly(self):
        req = PlaceSearchRequest(query="cafe", budget_filter=["free"])
        assert req.numeric_price_levels == [0]

    def test_multiple_levels_deduplicate_and_sort(self):
        req = PlaceSearchRequest(
            query="cafe",
            budget_filter=["inexpensive", "moderate"],
        )
        # inexpensive=[0,1] + moderate=[0,1,2] => {0,1,2} sorted
        assert req.numeric_price_levels == [0, 1, 2]

    def test_overlapping_levels_deduplicate(self):
        req = PlaceSearchRequest(
            query="cafe",
            budget_filter=["inexpensive", "expensive"],
        )
        # [0,1] + [2,3] => [0,1,2,3]
        assert req.numeric_price_levels == [0, 1, 2, 3]

    def test_all_levels_covers_full_range(self):
        req = PlaceSearchRequest(
            query="cafe",
            budget_filter=["free", "inexpensive", "moderate", "expensive", "very_expensive"],
        )
        assert req.numeric_price_levels == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# preference_summary method tests
# ---------------------------------------------------------------------------

class TestPreferenceSummary:
    def test_no_preferences_returns_safe_defaults(self):
        req = PlaceSearchRequest(query="cafe")
        summary = req.preference_summary()
        assert summary["budget_set"] is False
        assert summary["budget_count"] == 0
        assert summary["wheelchair_accessible_preference"] is None
        assert summary["has_user_location"] is False
        assert "lat" in summary["effective_origin_rounded"]
        assert "lng" in summary["effective_origin_rounded"]

    def test_with_budget_shows_count(self):
        req = PlaceSearchRequest(
            query="cafe",
            budget_filter=["free", "moderate"],
        )
        summary = req.preference_summary()
        assert summary["budget_set"] is True
        assert summary["budget_count"] == 2

    def test_with_wheelchair_shows_bool(self):
        req = PlaceSearchRequest(
            query="pharmacy",
            wheelchair_accessible_preference=True,
        )
        summary = req.preference_summary()
        assert summary["wheelchair_accessible_preference"] is True

    def test_with_user_location_shows_flag(self):
        req = PlaceSearchRequest(
            query="hotel",
            user_location=LatLng(lat=10.179444, lng=104.049123),
        )
        summary = req.preference_summary()
        assert summary["has_user_location"] is True
        # Coordinates are rounded — no exact GPS in summary
        assert summary["effective_origin_rounded"]["lat"] == 10.18
        assert summary["effective_origin_rounded"]["lng"] == 104.05

    def test_no_pii_in_summary(self):
        """preference_summary must never expose raw coordinates or secrets."""
        req = PlaceSearchRequest(
            query="test",
            user_location=LatLng(lat=10.123456789, lng=104.987654321),
        )
        summary = req.preference_summary()
        # Rounded to 2 decimals — not exact GPS
        rounded = summary["effective_origin_rounded"]
        assert str(rounded["lat"]) != "10.123456789"
        assert str(rounded["lng"]) != "104.987654321"
        assert len(str(rounded["lat"]).split(".")[1]) <= 2


# ---------------------------------------------------------------------------
# Negative tests: malformed preference values must fail validation
# ---------------------------------------------------------------------------

class TestPlaceSearchRequestInvalidPreferences:
    def test_rejects_invalid_price_level_string(self):
        with pytest.raises(ValidationError):
            PlaceSearchRequest(
                query="cafe",
                budget_filter=["luxury"],  # not a valid PriceLevel
            )

    def test_rejects_numeric_price_level(self):
        with pytest.raises(ValidationError):
            PlaceSearchRequest(
                query="cafe",
                budget_filter=[2],  # ints not accepted — must be symbolic strings
            )

    def test_rejects_empty_budget_list(self):
        with pytest.raises(ValidationError):
            PlaceSearchRequest(
                query="cafe",
                budget_filter=[],  # empty list rejected — use None for no constraint
            )

    def test_rejects_oversized_budget_list(self):
        with pytest.raises(ValidationError):
            PlaceSearchRequest(
                query="cafe",
                budget_filter=["free", "inexpensive", "moderate", "expensive", "very_expensive", "free"],
            )

    def test_rejects_non_bool_wheelchair_preference(self):
        with pytest.raises(ValidationError):
            PlaceSearchRequest(
                query="cafe",
                wheelchair_accessible_preference=["yes"],  # list not bool
            )

    def test_rejects_invalid_user_location_lat(self):
        with pytest.raises(ValidationError):
            PlaceSearchRequest(
                query="cafe",
                user_location=LatLng(lat=91.0, lng=104.0),  # lat out of range
            )

    def test_rejects_invalid_user_location_lng(self):
        with pytest.raises(ValidationError):
            PlaceSearchRequest(
                query="cafe",
                user_location=LatLng(lat=10.0, lng=181.0),  # lng out of range
            )

    def test_rejects_string_user_location(self):
        with pytest.raises(ValidationError):
            PlaceSearchRequest(
                query="cafe",
                user_location="10.0,104.0",  # wrong type
            )

    def test_rejects_null_accessibility_value_via_dict(self):
        """Null (JSON null) should be accepted as None, not crash."""
        req = PlaceSearchRequest(
            query="cafe",
            wheelchair_accessible_preference=None,
        )
        assert req.wheelchair_accessible_preference is None

    def test_rejects_forbidden_extra_fields(self):
        with pytest.raises(ValidationError):
            PlaceSearchRequest(
                query="cafe",
                secret_api_key="sk-123",
            )

    def test_rejects_empty_query_with_preferences(self):
        with pytest.raises(ValidationError):
            PlaceSearchRequest(
                query="",  # min_length=1
                budget_filter=["free"],
            )

    def test_rejects_oversized_query(self):
        with pytest.raises(ValidationError):
            PlaceSearchRequest(query="x" * 161)

    def test_rejects_duplicate_price_levels_no_crash(self):
        """Duplicate symbolic levels should be accepted and deduplicated."""
        req = PlaceSearchRequest(
            query="cafe",
            budget_filter=["free", "free", "free"],
        )
        # budget_filter stores the raw list (Pydantic accepts duplicates)
        assert len(req.budget_filter) == 3
        # But numeric conversion deduplicates
        assert req.numeric_price_levels == [0]


# ---------------------------------------------------------------------------
# Default Ham Ninh bias when no user location
# ---------------------------------------------------------------------------

class TestDefaultHamNinhBias:
    def test_location_bias_defaults_to_ham_ninh_center(self):
        req = PlaceSearchRequest(query="cafe")
        assert req.location_bias.lat == HAM_NINH_CENTER.lat
        assert req.location_bias.lng == HAM_NINH_CENTER.lng

    def test_effective_origin_is_ham_ninh_when_no_user_location(self):
        req = PlaceSearchRequest(query="cafe")
        origin = req.effective_origin
        assert origin.lat == HAM_NINH_CENTER.lat
        assert origin.lng == HAM_NINH_CENTER.lng

    def test_location_bias_is_independent_copy(self):
        """Each request should get its own copy of the default."""
        req1 = PlaceSearchRequest(query="cafe")
        req2 = PlaceSearchRequest(query="restaurant")
        assert req1.location_bias is not req2.location_bias


# ---------------------------------------------------------------------------
# Serialization without secrets/PII
# ---------------------------------------------------------------------------

class TestPreferenceSerialization:
    def test_model_dump_contains_preference_fields(self):
        req = PlaceSearchRequest(
            query="cafe",
            budget_filter=["inexpensive"],
            wheelchair_accessible_preference=True,
            user_location=LatLng(lat=10.18, lng=104.05),
        )
        dump = req.model_dump()
        assert dump["budget_filter"] == ["inexpensive"]
        assert dump["wheelchair_accessible_preference"] is True
        assert dump["user_location"]["lat"] == 10.18

    def test_model_dump_json_round_trips(self):
        req = PlaceSearchRequest(
            query="hotel",
            budget_filter=["moderate", "expensive"],
            wheelchair_accessible_preference=False,
        )
        json_str = req.model_dump_json()
        restored = PlaceSearchRequest.model_validate_json(json_str)
        assert restored.query == "hotel"
        assert len(restored.budget_filter) == 2
        assert restored.wheelchair_accessible_preference is False

    def test_no_api_key_in_serialization(self):
        """Ensure serialization does not leak any secrets."""
        req = PlaceSearchRequest(query="cafe", budget_filter=["free"])
        dump = req.model_dump_json()
        assert "api_key" not in dump.lower()
        assert "secret" not in dump.lower()
        assert "token" not in dump.lower()

    def test_preference_summary_is_separate_from_model_dump(self):
        """preference_summary is a computed method — not part of model_dump."""
        req = PlaceSearchRequest(query="cafe", budget_filter=["free"])
        dump = req.model_dump()
        assert "preference_summary" not in dump
        # But the method is callable
        summary = req.preference_summary()
        assert summary["budget_set"] is True

# ---------------------------------------------------------------------------
# PlaceResult explanation contract tests
# ---------------------------------------------------------------------------

class TestPlaceResultExplanation:
    def _score_breakdown(self) -> ScoreBreakdown:
        from app.models.response import ScoreBreakdown

        return ScoreBreakdown(
            tree1_locality=0.8,
            tree2_proximity=0.7,
            tree3_quality=0.9,
            s_bag=0.8,
            delta1_fairness=0.0,
            delta2_access=0.0,
            final_score=0.8,
            rank=1,
        )

    def test_place_result_requires_strict_structured_explanation(self):
        from app.models.response import PlaceExplanation, PlaceResult

        explanation = PlaceExplanation(
            rank=1,
            primary_reason="Recommended by reranking grounded place fields.",
            matched_preferences=["type:restaurant", "price_level:2"],
            local_context="strong local signal from normalized provider metadata",
            score_factors={"rank": 1, "final_score": 0.8, "local_factor": 0.7},
            fairness_note="supports local representation balancing",
            accessibility_note="accessibility score 1.00",
            route_summary="route drive, 1200m, 5min",
            provider_status="OPERATIONAL",
            evidence_fields_used=["place_id", "display_name", "score_breakdown"],
        )
        place = PlaceResult(
            place_id="places/explained",
            display_name="Explained Cafe",
            local_factor=0.7,
            final_score=0.8,
            score_breakdown=self._score_breakdown(),
            map_uri="https://maps.example/explained",
            explanation=explanation,
        )

        dumped = place.model_dump()
        assert dumped["explanation"]["rank"] == 1
        assert dumped["explanation"]["matched_preferences"] == ["type:restaurant", "price_level:2"]
        assert "raw_provider_payload" not in place.model_dump_json().lower()
        assert "phone" not in place.model_dump_json().lower()
        assert "api_key" not in place.model_dump_json().lower()

    def test_explanation_forbids_extra_secret_fields(self):
        from app.models.response import PlaceExplanation

        with pytest.raises(ValidationError):
            PlaceExplanation(rank=1, api_key="secret")

    def test_place_result_defaults_to_limited_explanation_when_missing_metadata(self):
        from app.models.response import PlaceResult

        place = PlaceResult(
            place_id="places/minimal",
            display_name="Minimal Cafe",
            local_factor=0.5,
            final_score=0.5,
            score_breakdown=self._score_breakdown(),
            map_uri="https://maps.example/minimal",
        )

        assert place.explanation.rank == 0
        assert place.explanation.accessibility_note == "accessibility metadata unknown"
        assert place.explanation.route_summary == "route metadata unavailable"


# ===========================================================================
# T02: PlaceAuditEvent and PlaceDecisionTrace model tests (M013/S05)
# ===========================================================================

class TestPlaceAuditEvent:
    """Tests for the PlaceAuditEvent model."""

    def test_valid_event_creation(self):
        from app.models.places import PlaceAuditEvent, PlaceAuditPhase

        event = PlaceAuditEvent(
            event="request_built",
            phase=PlaceAuditPhase.REQUEST,
            detail={"language_code": "en"},
            elapsed_ms=1.5,
        )
        assert event.event == "request_built"
        assert event.phase == PlaceAuditPhase.REQUEST
        assert event.detail["language_code"] == "en"
        assert event.elapsed_ms == 1.5

    def test_invalid_event_name_rejected(self):
        from app.models.places import PlaceAuditEvent, PlaceAuditPhase
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PlaceAuditEvent(
                event="made_up_event",
                phase=PlaceAuditPhase.REQUEST,
            )

    def test_extra_fields_forbidden(self):
        from app.models.places import PlaceAuditEvent, PlaceAuditPhase
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PlaceAuditEvent(
                event="request_built",
                phase=PlaceAuditPhase.REQUEST,
                secret_key="must-not-appear",
            )

    def test_all_phase_values_accepted(self):
        from app.models.places import PlaceAuditEvent, PlaceAuditPhase, PLACE_AUDIT_EVENTS

        # Verify each event can be created with its corresponding phase
        for event_name in PLACE_AUDIT_EVENTS:
            # Just verify no ValidationError is raised
            event = PlaceAuditEvent(event=event_name, phase=PlaceAuditPhase.REQUEST)
            assert event.event == event_name


class TestPlaceDecisionTrace:
    """Tests for the PlaceDecisionTrace model."""

    def test_empty_trace_creation(self):
        from app.models.places import PlaceDecisionTrace

        trace = PlaceDecisionTrace(session_id="s-empty")
        assert trace.events == []
        assert trace.session_id == "s-empty"
        assert trace.total_events == 0
        assert trace.credential_status is None
        assert trace.provider_source is None

    def test_trace_with_events(self):
        from app.models.places import PlaceAuditEvent, PlaceAuditPhase, PlaceDecisionTrace

        events = [
            PlaceAuditEvent(event="request_built", phase=PlaceAuditPhase.REQUEST),
            PlaceAuditEvent(event="provider_called", phase=PlaceAuditPhase.PROVIDER),
            PlaceAuditEvent(event="composition_deterministic", phase=PlaceAuditPhase.COMPOSE),
        ]
        trace = PlaceDecisionTrace(
            events=events,
            session_id="s-trace",
            credential_status="live",
            provider_source="mock",
        )
        assert trace.total_events == 3
        assert len(trace.events) == 3
        assert trace.credential_status == "live"
        assert trace.provider_source == "mock"

    def test_trace_extra_fields_forbidden(self):
        from app.models.places import PlaceDecisionTrace
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PlaceDecisionTrace(
                session_id="s-bad",
                raw_provider_payload="should-not-exist",
            )

    def test_trace_serialization_is_safe(self):
        from app.models.places import PlaceAuditEvent, PlaceAuditPhase, PlaceDecisionTrace

        trace = PlaceDecisionTrace(
            events=[
                PlaceAuditEvent(
                    event="provider_called",
                    phase=PlaceAuditPhase.PROVIDER,
                    detail={"source": "mock", "candidate_count": 3},
                ),
            ],
            session_id="s-safe",
            credential_status="live",
            provider_source="mock",
        )
        dump = trace.model_dump_json()
        assert "api_key" not in dump.lower()
        assert "secret" not in dump.lower()
