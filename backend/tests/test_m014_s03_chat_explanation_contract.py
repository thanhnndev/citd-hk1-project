"""M014-S03-T03: Wire explanation contract through chat and follow-up context.

These tests verify that the real AgentService → PlaceRecommendationService
chat path preserves ScoreBreakdown, PlaceExplanation, decision_trace,
reasoning_log, citations, and FollowUpContext end-to-end so a later
"why this place?" question can be answered from structured context.

Labels under test:
  chat_response_places      — response.places carry explanation + score_breakdown
  decision_trace            — provider source and credential status present
  reasoning_log             — safe counts/status, no secrets
  citations_empty           — place-only recommendations have citations=[]
  followup_context          — FollowUpContext records score_breakdown_keys + explanation_keys
  provider_failure          — non-OK provider produces empty places, safe diagnostics
  missing_optional_fields   — places with minimal explanation data still work
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
from app.models.response import ChatResponse, PlaceExplanation, PlaceResult, ScoreBreakdown
from agents.graph.agent_service import (
    AgentService,
    FollowUpContext,
    InMemoryAgentCheckpointer,
    _build_followup_context,
)
from agents.services.place_recommendation_service import (
    PLACE_RECOMMENDATION_INTENT,
    PlaceRecommendationService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ok_tool_response(
    query: str = "seafood",
    candidate_count: int = 2,
) -> PlaceToolResponse:
    """Build an OK tool response with realistic candidates."""
    candidates = [
        PlaceCandidate(
            place_id="places/ham-ninh-a",
            display_name="Quán Hải Sản A",
            types=["restaurant", "seafood_restaurant"],
            primary_type="seafood_restaurant",
            formatted_address="Ham Ninh, Phu Quoc",
            location=LatLng(lat=10.1794, lng=104.0491),
            rating=4.5,
            user_rating_count=128,
            price_level=2,
            open_now=True,
            business_status="OPERATIONAL",
            local_factor=0.8,
            map_uri="https://map.goong.io/?pid=ham-ninh-a",
        ),
        PlaceCandidate(
            place_id="places/ham-ninh-b",
            display_name="Nhà Hàng Biển Xanh",
            types=["restaurant", "seafood_restaurant"],
            primary_type="seafood_restaurant",
            formatted_address="Duong Dong, Phu Quoc",
            location=LatLng(lat=10.1800, lng=104.0500),
            rating=4.2,
            user_rating_count=85,
            price_level=1,
            open_now=False,
            business_status="OPERATIONAL",
            local_factor=0.6,
            map_uri="https://map.goong.io/?pid=ham-ninh-b",
        ),
    ]
    return PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=PlaceToolSource.MOCK,
        candidates=candidates[:candidate_count],
        request=PlaceSearchRequest(query=query),
        retrieved_at=datetime.now(UTC),
    )


def _make_service(places_tool_response: PlaceToolResponse) -> AgentService:
    """Build an AgentService with a mocked places tool returning the given response."""
    places_tool = AsyncMock()
    places_tool.text_search.return_value = places_tool_response
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    checkpointer = InMemoryAgentCheckpointer()
    return AgentService(
        retriever=None,
        place_recommendation_service=recommender,
        checkpointer=checkpointer,
        checkpoint_mode="test",
    ), checkpointer


# ---------------------------------------------------------------------------
# T03-1: ChatResponse places carry ScoreBreakdown and PlaceExplanation
# ---------------------------------------------------------------------------

class TestChatResponseExplanationContract:
    """Verify that the real chat path produces places with full explanation
    and score_breakdown data — not just bare PlaceResult stubs."""

    @pytest.mark.asyncio
    async def test_places_carry_score_breakdown_all_fields(self) -> None:
        """Each place in response.places must have a complete ScoreBreakdown."""
        tool_resp = _make_ok_tool_response()
        service, _ = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-sb",
            message="tìm quán hải sản ở Hàm Ninh",
            language="vi",
        )

        assert len(response.places) == 2
        for place in response.places:
            sb = place.score_breakdown
            assert isinstance(sb, ScoreBreakdown)
            assert sb.tree1_locality is not None
            assert sb.tree2_proximity is not None
            assert sb.tree3_quality is not None
            assert sb.s_bag is not None
            assert sb.delta1_fairness is not None
            assert sb.delta2_access is not None
            assert sb.final_score is not None
            assert sb.rank is not None
            assert isinstance(sb.rank, int)
            assert sb.rank >= 1

    @pytest.mark.asyncio
    async def test_places_carry_explanation_all_fields(self) -> None:
        """Each place must carry a PlaceExplanation with real provider data."""
        tool_resp = _make_ok_tool_response()
        service, _ = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-expl",
            message="tìm quán hải sản",
            language="vi",
        )

        assert len(response.places) >= 1
        for place in response.places:
            expl = place.explanation
            assert isinstance(expl, PlaceExplanation)
            # Core fields present
            assert expl.primary_reason, "primary_reason must not be empty"
            assert len(expl.primary_reason) <= 240
            assert isinstance(expl.matched_preferences, list)
            assert len(expl.matched_preferences) <= 10
            assert isinstance(expl.score_factors, dict)
            assert len(expl.score_factors) <= 12
            # Provider fields populated from real tool response
            assert expl.provider_source is not None, "provider_source must be set from tool"
            assert expl.provider_status is not None, "provider_status must be set from tool"
            assert expl.provider_source == "mock"

    @pytest.mark.asyncio
    async def test_explanation_no_frontend_fabrication(self) -> None:
        """Explanation text must not contain invented facts not derived from
        provider tool data. The primary_reason should reference actual
        candidate attributes (name, type, local_factor)."""
        tool_resp = _make_ok_tool_response()
        service, _ = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-nofab",
            message="tìm quán hải sản",
            language="vi",
        )

        for place in response.places:
            expl = place.explanation
            reason = expl.primary_reason.lower()
            # Should reference the place name or type from candidate data
            has_place_ref = (
                "hải sản" in reason or
                "biển xanh" in reason or
                "restaurant" in reason or
                "seafood" in reason or
                "local" in reason or
                "grounded" in reason or
                "recommended" in reason
            )
            assert has_place_ref, f"Explanation should reference place data, got: {expl.primary_reason}"


# ---------------------------------------------------------------------------
# T03-2: decision_trace contains credential/provider source
# ---------------------------------------------------------------------------

class TestDecisionTraceProviderSource:
    """Verify decision_trace exposes provider source and credential status
    so follow-up questions like 'where does this data come from?' can be
    answered from structured context."""

    @pytest.mark.asyncio
    async def test_decision_trace_has_provider_source(self) -> None:
        """decision_trace.provider_source must be set for OK responses."""
        tool_resp = _make_ok_tool_response()
        service, _ = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-dt-src",
            message="tìm quán hải sản",
            language="vi",
        )

        assert response.decision_trace is not None
        assert response.decision_trace.provider_source is not None
        assert response.decision_trace.provider_source == "mock"

    @pytest.mark.asyncio
    async def test_decision_trace_has_credential_status(self) -> None:
        """decision_trace.credential_status must be set."""
        tool_resp = _make_ok_tool_response()
        service, _ = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-dt-cred",
            message="tìm quán hải sản",
            language="vi",
        )

        assert response.decision_trace is not None
        assert response.decision_trace.credential_status is not None
        assert response.decision_trace.credential_status == "live"

    @pytest.mark.asyncio
    async def test_decision_trace_events_contain_provider_info(self) -> None:
        """decision_trace.events should contain provider_called and composition events."""
        tool_resp = _make_ok_tool_response()
        service, _ = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-dt-events",
            message="tìm quán hải sản",
            language="vi",
        )

        assert response.decision_trace is not None
        events = response.decision_trace.events
        event_types = {e.event for e in events}
        assert "provider_called" in event_types, f"Expected provider_called in {event_types}"
        # OK path emits composition_deterministic (or reranking_ensemble) for successful composition
        ok_events = {"composition_deterministic", "reranking_ensemble"}
        assert ok_events & event_types, f"Expected one of {ok_events} in {event_types}"


# ---------------------------------------------------------------------------
# T03-3: reasoning_log has safe counts/status, no secrets
# ---------------------------------------------------------------------------

class TestReasoningLogSafety:
    """Verify reasoning_log exposes safe diagnostics without leaking secrets."""

    @pytest.mark.asyncio
    async def test_reasoning_log_has_status_and_counts(self) -> None:
        """reasoning_log must contain status and candidate/result counts."""
        tool_resp = _make_ok_tool_response()
        service, _ = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-rl",
            message="tìm quán hải sản",
            language="vi",
        )

        assert response.reasoning_log is not None
        log = response.reasoning_log
        assert "place_recommendation" in log
        assert "status=ok" in log
        assert "candidate_count=" in log
        assert "result_count=" in log

    @pytest.mark.asyncio
    async def test_reasoning_log_no_secrets(self) -> None:
        """reasoning_log must not contain API keys, DSNs, or raw payloads."""
        tool_resp = _make_ok_tool_response()
        service, _ = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-rl-sec",
            message="tìm quán hải sản",
            language="vi",
        )

        log = response.reasoning_log or ""
        assert "api_key" not in log.lower()
        assert "secret" not in log.lower()
        assert "password" not in log.lower()
        assert "token=" not in log.lower()


# ---------------------------------------------------------------------------
# T03-4: citations remain empty for place-only recommendations
# ---------------------------------------------------------------------------

class TestCitationsEmptyForPlaceRecommendations:
    """Place-only recommendations must never produce citations."""

    @pytest.mark.asyncio
    async def test_citations_empty_with_places(self) -> None:
        """When places are returned, citations must be empty."""
        tool_resp = _make_ok_tool_response()
        service, _ = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-cite",
            message="tìm quán hải sản",
            language="vi",
        )

        assert response.places, "Expected places"
        assert response.citations == [], f"Expected empty citations, got {response.citations}"

    @pytest.mark.asyncio
    async def test_citations_empty_with_no_places(self) -> None:
        """Even when provider returns empty, citations must be empty."""
        tool_resp = PlaceToolResponse(
            status=PlaceToolStatus.EMPTY,
            source=PlaceToolSource.MOCK,
            candidates=[],
            request=PlaceSearchRequest(query="nonexistent"),
            retrieved_at=datetime.now(UTC),
        )
        service, _ = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-cite-empty",
            message="tìm quán không tồn tại",
            language="vi",
        )

        assert response.places == []
        assert response.citations == []


# ---------------------------------------------------------------------------
# T03-5: FollowUpContext records score_breakdown_keys + explanation_keys
# ---------------------------------------------------------------------------

class TestFollowupContextExplanationKeys:
    """Verify that FollowUpContext captures explanation and score keys from
    the real chat response so follow-up "why" questions can reference them."""

    @pytest.mark.asyncio
    async def test_followup_context_has_score_breakdown_keys(self) -> None:
        """After a place response, FollowUpContext must record score_breakdown_keys."""
        tool_resp = _make_ok_tool_response()
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-fu-sb",
            message="tìm quán hải sản",
            language="vi",
        )

        # Verify context was saved
        ctx = await cp.load_context("s-fu-sb")
        assert ctx is not None
        assert ctx.is_populated is True
        assert "final_score" in ctx.score_breakdown_keys
        assert "tree1_locality" in ctx.score_breakdown_keys
        assert "rank" in ctx.score_breakdown_keys

    @pytest.mark.asyncio
    async def test_followup_context_has_explanation_keys(self) -> None:
        """After a place response, FollowUpContext must record explanation_keys."""
        tool_resp = _make_ok_tool_response()
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-fu-expl",
            message="tìm quán hải sản",
            language="vi",
        )

        ctx = await cp.load_context("s-fu-expl")
        assert ctx is not None
        assert "primary_reason" in ctx.explanation_keys
        assert "local_context" in ctx.explanation_keys
        assert "provider_source" in ctx.explanation_keys
        assert "provider_status" in ctx.explanation_keys

    @pytest.mark.asyncio
    async def test_followup_context_place_ids_and_names(self) -> None:
        """FollowUpContext must capture place IDs and display names."""
        tool_resp = _make_ok_tool_response()
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-fu-places",
            message="tìm quán hải sản",
            language="vi",
        )

        ctx = await cp.load_context("s-fu-places")
        assert ctx is not None
        assert len(ctx.place_ids) >= 1
        assert len(ctx.place_display_names) >= 1
        assert "places/ham-ninh-a" in ctx.place_ids
        assert "Quán Hải Sản A" in ctx.place_display_names

    @pytest.mark.asyncio
    async def test_followup_context_roundtrip_via_build(self) -> None:
        """_build_followup_context must extract explanation_keys from a
        real ChatResponse with populated places."""
        tool_resp = _make_ok_tool_response()
        service, _ = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-fu-build",
            message="tìm quán hải sản",
            language="vi",
        )

        ctx = _build_followup_context(response)
        assert ctx.is_populated is True
        assert len(ctx.explanation_keys) > 0, "explanation_keys must not be empty"
        assert len(ctx.score_breakdown_keys) > 0, "score_breakdown_keys must not be empty"
        # Verify keys come from actual model fields
        for key in ctx.explanation_keys:
            assert hasattr(PlaceExplanation, key) or key in PlaceExplanation.model_fields, (
                f"explanation_key '{key}' is not a valid PlaceExplanation field"
            )


# ---------------------------------------------------------------------------
# T03-6: Failure Modes (Q5) — provider failure / empty / credential-blocked
# ---------------------------------------------------------------------------

class TestProviderFailureModes:
    """Failure mode tests: provider errors must produce safe diagnostics
    with no places, and malformed data must be rejected by Pydantic."""

    @pytest.mark.asyncio
    async def test_upstream_error_no_places_safe_diagnostics(self) -> None:
        """UPSTREAM_ERROR must return empty places and safe message."""
        tool_resp = PlaceToolResponse(
            status=PlaceToolStatus.UPSTREAM_ERROR,
            source=PlaceToolSource.GOOGLE_PLACES,
            candidates=[],
            request=PlaceSearchRequest(query="seafood"),
            retrieved_at=datetime.now(UTC),
        )
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-fail-err",
            message="tìm nhà hàng",
            language="vi",
        )

        assert response.places == []
        assert response.citations == []
        assert response.intent == PLACE_RECOMMENDATION_INTENT
        assert response.reasoning_log is not None
        assert "upstream_error" in response.reasoning_log
        # No fabricated place data
        assert response.message  # honest unavailable message

    @pytest.mark.asyncio
    async def test_credentials_blocked_no_places_safe_message(self) -> None:
        """CREDENTIALS_BLOCKED must return empty places and honest message."""
        tool_resp = PlaceToolResponse(
            status=PlaceToolStatus.CREDENTIALS_BLOCKED,
            source=PlaceToolSource.GOOGLE_PLACES,
            candidates=[],
            request=PlaceSearchRequest(query="seafood"),
            retrieved_at=datetime.now(UTC),
        )
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-fail-cred",
            message="tìm nhà hàng",
            language="vi",
        )

        assert response.places == []
        assert response.citations == []
        assert response.intent == PLACE_RECOMMENDATION_INTENT
        assert "thiếu cấu hình" in response.message

    @pytest.mark.asyncio
    async def test_empty_response_followup_context_not_populated(self) -> None:
        """Empty provider response → follow-up context should not be populated
        (no place data to reference in follow-ups)."""
        tool_resp = PlaceToolResponse(
            status=PlaceToolStatus.EMPTY,
            source=PlaceToolSource.MOCK,
            candidates=[],
            request=PlaceSearchRequest(query="nonexistent"),
            retrieved_at=datetime.now(UTC),
        )
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-fail-empty-ctx",
            message="tìm quán không tồn tại",
            language="vi",
        )

        ctx = await cp.load_context("s-fail-empty-ctx")
        # Context may exist but should not have place data
        if ctx is not None:
            assert ctx.place_ids == []
            assert ctx.place_display_names == []

    @pytest.mark.asyncio
    async def test_malformed_explanation_rejected_by_pydantic(self) -> None:
        """Malformed explanation data (extra fields) must be rejected by
        Pydantic's extra='forbid' rather than silently serialized."""
        with pytest.raises(Exception):  # ValidationError
            PlaceExplanation(
                rank=1,
                primary_reason="test",
                unknown_field="should_be_rejected",  # extra='forbid'
            )

    @pytest.mark.asyncio
    async def test_malformed_score_breakdown_rejected_by_pydantic(self) -> None:
        """ScoreBreakdown missing required fields must fail Pydantic validation."""
        with pytest.raises(Exception):  # ValidationError
            ScoreBreakdown(
                tree1_locality=0.5,
                # missing required fields
            )


# ---------------------------------------------------------------------------
# T03-7: Load Profile (Q6) — bounded keys, no full payloads
# ---------------------------------------------------------------------------

class TestLoadProfileBoundedContext:
    """Verify follow-up context stores bounded keys/names only, not full
    payloads or raw provider data."""

    @pytest.mark.asyncio
    async def test_explanation_keys_bounded(self) -> None:
        """explanation_keys must be capped (max 10) to avoid bloating context."""
        tool_resp = _make_ok_tool_response(candidate_count=5)
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-load-expl",
            message="tìm quán hải sản",
            language="vi",
        )

        ctx = await cp.load_context("s-load-expl")
        assert ctx is not None
        assert len(ctx.explanation_keys) <= 10

    @pytest.mark.asyncio
    async def test_score_breakdown_keys_bounded(self) -> None:
        """score_breakdown_keys must be capped (max 10)."""
        tool_resp = _make_ok_tool_response(candidate_count=5)
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-load-sb",
            message="tìm quán hải sản",
            language="vi",
        )

        ctx = await cp.load_context("s-load-sb")
        assert ctx is not None
        assert len(ctx.score_breakdown_keys) <= 10

    @pytest.mark.asyncio
    async def test_reasoning_log_summary_bounded(self) -> None:
        """reasoning_log_summary in FollowUpContext must be truncated."""
        tool_resp = _make_ok_tool_response()
        service, _ = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-load-log",
            message="tìm quán hải sản",
            language="vi",
        )

        ctx = _build_followup_context(response)
        if ctx.reasoning_log_summary is not None:
            assert len(ctx.reasoning_log_summary) <= 500

    @pytest.mark.asyncio
    async def test_no_raw_provider_data_in_context(self) -> None:
        """FollowUpContext must not contain raw provider payloads."""
        tool_resp = _make_ok_tool_response()
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-load-noraw",
            message="tìm quán hải sản",
            language="vi",
        )

        ctx = await cp.load_context("s-load-noraw")
        assert ctx is not None
        ctx_dict = ctx.to_dict()
        dump = str(ctx_dict).lower()
        assert "api_key" not in dump
        assert "raw_payload" not in dump


# ---------------------------------------------------------------------------
# T03-8: Negative Tests (Q7) — missing optional explanation fields
# ---------------------------------------------------------------------------

class TestMissingOptionalExplanationFields:
    """Verify that places with minimal/missing optional explanation fields
    still serialize correctly and don't break follow-up context."""

    @pytest.mark.asyncio
    async def test_place_with_default_explanation_serializes(self) -> None:
        """A PlaceResult with default PlaceExplanation must serialize."""
        place = PlaceResult(
            place_id="places/minimal",
            display_name="Minimal Place",
            formatted_address="Test Address",
            location=LatLng(lat=10.0, lng=104.0),
            types=["restaurant"],
            local_factor=0.5,
            final_score=0.5,
            score_breakdown=ScoreBreakdown(
                tree1_locality=0.5,
                tree2_proximity=0.5,
                tree3_quality=0.5,
                s_bag=0.5,
                delta1_fairness=0.0,
                delta2_access=0.0,
                final_score=0.5,
                rank=1,
            ),
            map_uri="https://maps.example/minimal",
            # explanation uses default PlaceExplanation()
        )
        dump = place.model_dump()
        assert "explanation" in dump
        assert dump["explanation"]["rank"] == 0
        assert dump["explanation"]["primary_reason"]  # default text

    @pytest.mark.asyncio
    async def test_build_context_with_default_explanation(self) -> None:
        """_build_followup_context must handle places with default explanations."""
        place = PlaceResult(
            place_id="places/minimal",
            display_name="Minimal Place",
            formatted_address="Test",
            location=LatLng(lat=10.0, lng=104.0),
            types=["restaurant"],
            local_factor=0.5,
            final_score=0.5,
            score_breakdown=ScoreBreakdown(
                tree1_locality=0.5,
                tree2_proximity=0.5,
                tree3_quality=0.5,
                s_bag=0.5,
                delta1_fairness=0.0,
                delta2_access=0.0,
                final_score=0.5,
                rank=1,
            ),
            map_uri="https://maps.example/minimal",
        )
        response = ChatResponse(
            session_id="s-min",
            message="test",
            places=[place],
            citations=[],
            intent=PLACE_RECOMMENDATION_INTENT,
            latency_ms=50.0,
        )

        ctx = _build_followup_context(response)
        assert ctx.is_populated is True
        assert "places/minimal" in ctx.place_ids
        # Default explanation has all fields — keys extracted correctly
        assert len(ctx.explanation_keys) > 0

    @pytest.mark.asyncio
    async def test_followup_with_missing_provider_status(self) -> None:
        """Follow-up context with missing provider_status must still work."""
        place = PlaceResult(
            place_id="places/noprov",
            display_name="No Provider Place",
            formatted_address="Test",
            location=LatLng(lat=10.0, lng=104.0),
            types=["restaurant"],
            local_factor=0.5,
            final_score=0.5,
            score_breakdown=ScoreBreakdown(
                tree1_locality=0.5,
                tree2_proximity=0.5,
                tree3_quality=0.5,
                s_bag=0.5,
                delta1_fairness=0.0,
                delta2_access=0.0,
                final_score=0.5,
                rank=1,
            ),
            map_uri="https://maps.example/noprov",
        )
        response = ChatResponse(
            session_id="s-noprov",
            message="test",
            places=[place],
            citations=[],
            intent=PLACE_RECOMMENDATION_INTENT,
            latency_ms=50.0,
            decision_trace=None,  # No decision trace → no provider_source/status
        )

        ctx = _build_followup_context(response)
        assert ctx.is_populated is True
        assert ctx.provider_source is None
        assert ctx.provider_status is None
        # Follow-up still works for place name references
        from agents.graph.agent_service import resolve_followup_decision
        decision = resolve_followup_decision(
            "No Provider Place có mở không?", ctx
        )
        assert decision == "structured_context"
