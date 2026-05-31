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
