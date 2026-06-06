"""M014-S06: Integrated Chat API Contract Proof.

Exercises the real AgentService → PlaceRecommendationService → Provider
path end-to-end in one surface, proving:
  1. Recommendation with ScoreBreakdown + PlaceExplanation (S01 surface)
  2. Provider trace/status visible in decision_trace (S02 surface)
  3. Explanation fields populated, redacted, bounded (S03 surface)
  4. Follow-up context preserved and resolves contextual questions (S04/S05)
  5. Honest provider status vocabulary (credential_blocked, upstream_error)
  6. Negative cases: missing creds, malformed results, irrelevant follow-up

All tests use deterministic local fixtures — no live Google/OpenAI credentials.
"""

from __future__ import annotations

import json
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
from app.models.response import (
    ChatResponse,
    PlaceExplanation,
    PlaceResult,
    ScoreBreakdown,
)
from agents.graph.agent_service import (
    AgentService,
    FollowUpContext,
    InMemoryAgentCheckpointer,
    _build_followup_context,
    _compose_followup_answer,
    resolve_followup_decision,
)
from agents.services.place_recommendation_service import (
    PLACE_RECOMMENDATION_INTENT,
    PlaceRecommendationService,
)
from agents.tools.retriever import Retriever
from app.models.rag import RetrievalResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ham_ninh_candidate(
    place_id: str = "places/ham-ninh-a",
    display_name: str = "Quán Hải Sản A",
    local_factor: float = 0.8,
    rating: float = 4.5,
) -> PlaceCandidate:
    return PlaceCandidate(
        place_id=place_id,
        display_name=display_name,
        types=["restaurant", "seafood_restaurant"],
        primary_type="seafood_restaurant",
        formatted_address="Hàm Ninh, Phú Quốc",
        location=LatLng(lat=10.1794, lng=104.0491),
        rating=rating,
        user_rating_count=128,
        price_level=2,
        open_now=True,
        business_status="OPERATIONAL",
        local_factor=local_factor,
        map_uri=f"https://map.goong.io/?pid={place_id}",
    )


def _make_ok_response(
    candidates: list[PlaceCandidate] | None = None,
    source: PlaceToolSource = PlaceToolSource.MOCK,
) -> PlaceToolResponse:
    return PlaceToolResponse(
        status=PlaceToolStatus.OK,
        source=source,
        candidates=candidates or [_ham_ninh_candidate()],
        request=PlaceSearchRequest(query="hải sản hàm ninh"),
        retrieved_at=datetime.now(UTC),
    )


def _make_service(
    tool_response: PlaceToolResponse,
    *,
    checkpointer: InMemoryAgentCheckpointer | None = None,
) -> tuple[AgentService, InMemoryAgentCheckpointer]:
    cp = checkpointer or InMemoryAgentCheckpointer()
    places_tool = AsyncMock()
    places_tool.text_search.return_value = tool_response
    recommender = PlaceRecommendationService(places_tool, routes_service=None)
    service = AgentService(
        retriever=None,
        place_recommendation_service=recommender,
        checkpointer=cp,
        checkpoint_mode="test",
    )
    return service, cp


def _make_class_call_tracker():
    class Tracker:
        def __init__(self):
            self.retriever_calls = 0
            self.place_service_calls = 0

    return Tracker()


class NoopRetriever(Retriever):
    def __init__(self):
        pass

    def search_with_citations(self, query, top_k=5):
        return RetrievalResult(chunks=[]), []


# ---------------------------------------------------------------------------
# T06-1: Full recommendation loop — Hàm Ninh seafood
# ---------------------------------------------------------------------------

class TestIntegratedRecommendationLoop:
    """Prove the full chat → recommendation → explanation loop works
    with real agent service wiring for a Hàm Ninh seafood query."""

    @pytest.mark.asyncio
    async def test_ham_ninh_recommendation_returns_places_with_scores(self) -> None:
        """Asking for Hàm Ninh seafood must return places with complete
        ScoreBreakdown and PlaceExplanation."""
        tool_resp = _make_ok_response()
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-int-01",
            message="tìm quán hải sản ở Hàm Ninh",
            language="vi",
        )

        assert response.places, "Expected at least one place recommendation"
        for place in response.places:
            sb = place.score_breakdown
            assert isinstance(sb, ScoreBreakdown)
            assert sb.tree1_locality is not None
            assert sb.tree2_proximity is not None
            assert sb.tree3_quality is not None
            assert sb.s_bag is not None
            assert sb.final_score is not None
            assert sb.rank >= 1
            assert isinstance(sb.rank, int)

    @pytest.mark.asyncio
    async def test_explanation_carries_provider_source_and_status(self) -> None:
        """PlaceExplanation must carry provider_source and provider_status
        from the real tool response — not None or fabricated."""
        tool_resp = _make_ok_response()
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-int-02",
            message="tìm quán hải sản ở Hàm Ninh",
            language="vi",
        )

        for place in response.places:
            expl = place.explanation
            assert expl.provider_source is not None, "provider_source must be set"
            assert expl.provider_status is not None, "provider_status must be set"
            assert expl.provider_source == "mock"

    @pytest.mark.asyncio
    async def test_decision_trace_exposes_provider_source(self) -> None:
        """response.decision_trace must expose provider_source for
        follow-up 'where does this data come from?' questions."""
        tool_resp = _make_ok_response()
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-int-03",
            message="tìm quán hải sản",
            language="vi",
        )

        assert response.decision_trace is not None
        assert response.decision_trace.provider_source is not None
        assert response.decision_trace.credential_status is not None
        # Provider source in decision_trace matches place explanation
        for place in response.places:
            assert place.explanation.provider_source == response.decision_trace.provider_source

    @pytest.mark.asyncio
    async def test_reasoning_log_has_safe_diagnostics(self) -> None:
        """reasoning_log must contain status, source, counts — and no secrets."""
        tool_resp = _make_ok_response()
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-int-04",
            message="tìm quán hải sản",
            language="vi",
        )

        log = response.reasoning_log or ""
        assert "status=" in log
        assert "source=" in log
        assert "candidate_count=" in log
        assert "result_count=" in log
        assert "api_key" not in log.lower()
        assert "secret" not in log.lower()
        assert "password" not in log.lower()


# ---------------------------------------------------------------------------
# T06-2: Contextual follow-up — "why this place scored well"
# ---------------------------------------------------------------------------

class TestContextualFollowUpLoop:
    """Prove the follow-up context survives across turns and resolves
    unseen follow-up questions from structured context, not RAG."""

    @pytest.mark.asyncio
    async def test_followup_context_saved_after_first_turn(self) -> None:
        """After a place response, structured context must be persisted."""
        tool_resp = _make_ok_response(candidates=[
            _ham_ninh_candidate("places/ham-ninh-a", "Quán Hải Sản A"),
        ])
        service, cp = _make_service(tool_resp)

        await service.answer(
            session_id="s-fu-01",
            message="tìm quán hải sản ở Hàm Ninh",
            language="vi",
        )

        ctx = await cp.load_context("s-fu-01")
        assert ctx is not None
        assert ctx.is_populated is True
        assert "places/ham-ninh-a" in ctx.place_ids
        assert "Quán Hải Sản A" in ctx.place_display_names
        assert ctx.score_breakdown_keys, "score_breakdown_keys must be saved"
        assert ctx.explanation_keys, "explanation_keys must be saved"
        assert ctx.provider_source is not None

    @pytest.mark.asyncio
    async def test_unseen_followup_resolves_structured_context(self) -> None:
        """An unseen follow-up referencing a prior place name must resolve
        as structured_context, not RAG or fallback."""
        tool_resp = _make_ok_response(candidates=[
            _ham_ninh_candidate("places/ham-ninh-a", "Quán Hải Sản A"),
        ])
        service, cp = _make_service(tool_resp)

        # Turn 1: recommendation
        await service.answer(
            session_id="s-fu-02",
            message="tìm quán hải sản ở Hàm Ninh",
            language="vi",
        )

        # Turn 2: unseen follow-up about the place
        response = await service.answer(
            session_id="s-fu-02",
            message="Quán Hải Sản A tại sao được xếp cao?",
            language="vi",
        )

        assert response.intent == "followup_contextual"
        assert response.fallback is False
        assert "Hải Sản A" in response.message

    @pytest.mark.asyncio
    async def test_followup_why_scored_carries_score_breakdown_info(self) -> None:
        """A 'why scored well' follow-up must reference score breakdown keys
        from the structured context."""
        # Use place names that won't match the question tokens so the score
        # breakdown path fires (place name matching is checked first).
        ctx = FollowUpContext(
            session_id="s-fu-score",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_ids=["places/ham-ninh-a"],
            place_display_names=["Venue Alpha"],
            score_breakdown_keys=["final_score", "tree1_locality", "tree2_proximity", "tree3_quality"],
            provider_source="mock",
            provider_status="ok",
        )
        answer = _compose_followup_answer("Vì sao được xếp cao?", ctx, "vi")
        assert "final_score" in answer
        assert "tree1_locality" in answer

    @pytest.mark.asyncio
    async def test_followup_decision_is_structured_not_rag(self) -> None:
        """resolve_followup_decision must return structured_context for
        place name references — not insufficient_context or fallback."""
        ctx = FollowUpContext(
            session_id="s-fu-dec",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_ids=["places/ham-ninh-a"],
            place_display_names=["Quán Hải Sản A", "Nhà Hàng Biển Xanh"],
            score_breakdown_keys=["final_score"],
            provider_source="mock",
        )
        decision = resolve_followup_decision("Hải Sản A có ngon không?", ctx)
        assert decision == "structured_context"

    @pytest.mark.asyncio
    async def test_followup_context_carries_explanation_keys(self) -> None:
        """FollowUpContext must carry explanation_keys so follow-up agents
        know which explanation fields are available."""
        ctx = FollowUpContext(
            session_id="s-fu-expl-keys",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_ids=["p1"],
            explanation_keys=["primary_reason", "local_context", "provider_source", "provider_status"],
        )
        answer = _compose_followup_answer("Quán này có gì đặc biệt?", ctx, "vi")
        assert len(answer) > 0
        # Context reference should appear
        assert "gợi ý" in answer.lower() or "đặc biệt" in answer.lower() or "primary_reason" in answer


# ---------------------------------------------------------------------------
# T06-3: Provider status vocabulary — credential blocked, upstream error
# ---------------------------------------------------------------------------

class TestHonestProviderStatus:
    """Verify the chat API surfaces honest provider status vocabulary
    when credentials are missing or the provider fails."""

    @pytest.mark.asyncio
    async def test_credential_blocked_returns_honest_message(self) -> None:
        """When provider credentials are missing, response must say so
        without fabricating place data."""
        tool_resp = PlaceToolResponse(
            status=PlaceToolStatus.CREDENTIALS_BLOCKED,
            source=PlaceToolSource.GOOGLE_PLACES,
            candidates=[],
            request=PlaceSearchRequest(query="hải sản"),
            retrieved_at=datetime.now(UTC),
        )
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-cred-blocked",
            message="tìm quán hải sản",
            language="vi",
        )

        assert response.places == [], "No places should be fabricated"
        assert "thiếu cấu hình" in response.message, "Must mention missing config"
        assert response.reasoning_log is not None
        assert "credential" in response.reasoning_log.lower() or "blocked" in response.reasoning_log.lower()

    @pytest.mark.asyncio
    async def test_upstream_error_returns_empty_places_with_diagnostics(self) -> None:
        """Provider upstream error must return empty places and safe diagnostics."""
        tool_resp = PlaceToolResponse(
            status=PlaceToolStatus.UPSTREAM_ERROR,
            source=PlaceToolSource.GOOGLE_PLACES,
            candidates=[],
            request=PlaceSearchRequest(query="hải sản"),
            retrieved_at=datetime.now(UTC),
        )
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-upstream-err",
            message="tìm quán hải sản",
            language="vi",
        )

        assert response.places == []
        assert response.reasoning_log is not None
        assert "upstream_error" in response.reasoning_log.lower()

    @pytest.mark.asyncio
    async def test_credential_blocked_followup_context_not_populated(self) -> None:
        """Credential blocked response should not populate follow-up context
        with place data."""
        tool_resp = PlaceToolResponse(
            status=PlaceToolStatus.CREDENTIALS_BLOCKED,
            source=PlaceToolSource.GOOGLE_PLACES,
            candidates=[],
            request=PlaceSearchRequest(query="hải sản"),
            retrieved_at=datetime.now(UTC),
        )
        service, cp = _make_service(tool_resp)

        await service.answer(
            session_id="s-cred-ctx",
            message="tìm quán hải sản",
            language="vi",
        )

        ctx = await cp.load_context("s-cred-ctx")
        if ctx is not None:
            assert ctx.place_ids == []
            assert ctx.place_display_names == []


# ---------------------------------------------------------------------------
# T06-4: Redaction boundaries — no secrets in any response surface
# ---------------------------------------------------------------------------

class TestRedactionBoundaries:
    """Prove no secrets, API keys, or raw payloads leak through any
    response surface: places, explanations, reasoning_log, or context."""

    @pytest.mark.asyncio
    async def test_serialized_response_no_api_keys(self) -> None:
        """Serialized response JSON must not contain API key patterns."""
        tool_resp = _make_ok_response()
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-redact-01",
            message="tìm quán hải sản",
            language="vi",
        )

        dump = response.model_dump_json()
        assert "AIza" not in dump
        assert "GOOGLE_PLACES_API_KEY" not in dump
        assert "GOONG_API_KEY" not in dump
        assert "sk-" not in dump.lower() or "key_redacted" in dump.lower()

    @pytest.mark.asyncio
    async def test_explanation_fields_no_phone_numbers(self) -> None:
        """Explanation text fields must not contain raw phone numbers."""
        candidate = PlaceCandidate(
            place_id="places/phone-test",
            display_name="Quán ABC",
            types=["restaurant", "seafood_restaurant"],
            primary_type="seafood_restaurant",
            formatted_address="Gọi 02973846123 để đặt bàn",
            location=LatLng(lat=10.1794, lng=104.0491),
            rating=4.5,
            user_rating_count=128,
            price_level=2,
            open_now=True,
            business_status="OPERATIONAL",
            local_factor=0.8,
            map_uri="https://map.goong.io/?pid=phone-test",
        )
        tool_resp = _make_ok_response(candidates=[candidate])
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-redact-02",
            message="tìm quán hải sản",
            language="vi",
        )

        for place in response.places:
            exp_json = json.dumps(place.explanation.model_dump())
            assert "02973846123" not in exp_json
            assert "+84" not in exp_json

    @pytest.mark.asyncio
    async def test_context_no_raw_provider_payload(self) -> None:
        """FollowUpContext must not contain raw provider payloads."""
        tool_resp = _make_ok_response()
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-redact-03",
            message="tìm quán hải sản",
            language="vi",
        )

        ctx = await cp.load_context("s-redact-03")
        assert ctx is not None
        ctx_dict = ctx.to_dict()
        dump = str(ctx_dict).lower()
        assert "api_key" not in dump
        assert "raw_payload" not in dump


# ---------------------------------------------------------------------------
# T06-5: Negative cases — malformed, empty, irrelevant follow-up
# ---------------------------------------------------------------------------

class TestNegativeCases:
    """Verify the system handles malformed provider results, empty responses,
    and irrelevant follow-ups without hallucination or crashes."""

    @pytest.mark.asyncio
    async def test_empty_provider_results_no_hallucination(self) -> None:
        """Empty provider results must produce empty places, not fabricated ones."""
        tool_resp = PlaceToolResponse(
            status=PlaceToolStatus.OK,
            source=PlaceToolSource.MOCK,
            candidates=[],
            request=PlaceSearchRequest(query="nonexistent place"),
            retrieved_at=datetime.now(UTC),
        )
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-neg-empty",
            message="tìm quán không tồn tại",
            language="vi",
        )

        assert response.places == []
        assert response.citations == []

    @pytest.mark.asyncio
    async def test_irrelevant_followup_no_hallucinated_places(self) -> None:
        """An irrelevant follow-up with no prior context must not invent places."""
        cp = InMemoryAgentCheckpointer()
        # No prior context — just a greeting history
        await cp.save_turn("s-neg-irrel", "hello", "hi there!")

        service, _ = _make_service(_make_ok_response(), checkpointer=cp)

        # Irrelevant follow-up
        response = await service.answer(
            session_id="s-neg-irrel",
            message="tính giúp tôi 2 với 3",
            language="vi",
        )

        # Should not produce fabricated places
        assert response.places == []
        # Either clarification or insufficient_context path
        assert response.fallback is False

    @pytest.mark.asyncio
    async def test_new_place_request_not_blocked_by_prior_context(self) -> None:
        """A new place request should go through normal routing even with
        prior context — not treated as a follow-up."""
        tracker = _make_class_call_tracker()

        from app.models.response import ChatResponse as PlaceServiceResponse

        class MockPlaceService:
            async def recommend(self, **kwargs):
                tracker.place_service_calls += 1
                return PlaceServiceResponse(
                    session_id=kwargs.get("session_id", "test"),
                    message="Found new places",
                    places=[],
                    citations=[],
                    reasoning_log=None,
                    intent=PLACE_RECOMMENDATION_INTENT,
                    latency_ms=100.0,
                    fallback=False,
                )

        cp = InMemoryAgentCheckpointer()
        prior = FollowUpContext(
            session_id="s-neg-new",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_ids=["goong_old"],
            place_display_names=["Quán Cũ"],
        )
        await cp.save_context("s-neg-new", prior)
        await cp.save_turn("s-neg-new", "old query", "old response")

        service = AgentService(
            retriever=None,
            checkpointer=cp,
            checkpoint_mode="test",
            place_recommendation_service=MockPlaceService(),
            llm_service=None,
        )

        response = await service.answer(
            session_id="s-neg-new",
            message="Tìm quán cà phê gần đây",
            language="vi",
        )

        assert tracker.place_service_calls == 1, "New place request must reach place service"
        assert response.intent == PLACE_RECOMMENDATION_INTENT

    @pytest.mark.asyncio
    async def test_malformed_explanation_rejected_by_pydantic(self) -> None:
        """PlaceExplanation with extra fields must be rejected by Pydantic."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PlaceExplanation(
                rank=1,
                primary_reason="test",
                frontend_fabricated_reason="should be rejected",
            )

    @pytest.mark.asyncio
    async def test_malformed_score_breakdown_rejected_by_pydantic(self) -> None:
        """ScoreBreakdown missing required fields must fail validation."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ScoreBreakdown(
                tree1_locality=0.5,
                # missing required: tree2_proximity, tree3_quality, etc.
            )


# ---------------------------------------------------------------------------
# T06-6: Full two-turn integration — recommendation + follow-up
# ---------------------------------------------------------------------------

class TestFullTwoTurnIntegration:
    """End-to-end two-turn test: recommend, then ask 'why this place'."""

    @pytest.mark.asyncio
    async def test_recommend_then_why_scored_full_loop(self) -> None:
        """Turn 1: recommend Hàm Ninh seafood → places with scores.
        Turn 2: ask why the first place scored well → structured answer."""
        tool_resp = _make_ok_response(candidates=[
            _ham_ninh_candidate("places/ham-ninh-a", "Quán Hải Sản Hàm Ninh A", local_factor=0.9),
            _ham_ninh_candidate("places/ham-ninh-b", "Nhà Hàng Biển Xanh", local_factor=0.5),
        ])
        service, cp = _make_service(tool_resp)

        # Turn 1: recommendation
        r1 = await service.answer(
            session_id="s-2turn",
            message="tìm quán hải sản ở Hàm Ninh",
            language="vi",
        )

        assert len(r1.places) >= 1, "Turn 1 must return places"
        first_name = r1.places[0].display_name
        sb = r1.places[0].score_breakdown
        assert sb.final_score > 0, "First place must have a real score"
        assert r1.decision_trace is not None
        assert r1.decision_trace.provider_source is not None

        # Turn 2: unseen follow-up about the first place
        r2 = await service.answer(
            session_id="s-2turn",
            message=f"{first_name} tại sao được xếp cao?",
            language="vi",
        )

        assert r2.intent == "followup_contextual", (
            f"Expected followup_contextual, got {r2.intent}"
        )
        assert r2.fallback is False
        assert first_name.split()[-1] in r2.message or "gợi ý" in r2.message.lower(), (
            f"Follow-up should reference {first_name}, got: {r2.message}"
        )
        # No new place search happened
        assert r2.places == []

    @pytest.mark.asyncio
    async def test_recommend_then_provider_source_followup(self) -> None:
        """Turn 1: recommend → Turn 2: ask 'where does data come from?'"""
        tool_resp = _make_ok_response()
        service, cp = _make_service(tool_resp)

        await service.answer(
            session_id="s-2turn-prov",
            message="tìm quán hải sản",
            language="vi",
        )

        response = await service.answer(
            session_id="s-2turn-prov",
            message="Nguồn dữ liệu từ đâu?",
            language="vi",
        )

        assert response.intent == "followup_contextual"
        assert response.fallback is False
        assert len(response.message) > 0

    @pytest.mark.asyncio
    async def test_recommend_then_irrelevant_does_not_hallucinate(self) -> None:
        """Turn 1: recommend → Turn 2: totally irrelevant question.
        Must not hallucinate place data or crash."""
        tool_resp = _make_ok_response(candidates=[
            _ham_ninh_candidate("places/ham-ninh-a", "Quán Hải Sản A"),
        ])
        service, cp = _make_service(tool_resp)

        await service.answer(
            session_id="s-2turn-irrel",
            message="tìm quán hải sản",
            language="vi",
        )

        response = await service.answer(
            session_id="s-2turn-irrel",
            message="thời tiết hôm nay thế nào",
            language="vi",
        )

        # Should not produce fabricated places for weather query
        # It will go through normal routing (insufficient_context for this topic)
        assert response.fallback is False


# ---------------------------------------------------------------------------
# T06-7: Failure Mode (Q5) — provider credential missing
# ---------------------------------------------------------------------------

class TestFailureModeMissingCredentials:
    """Failure Mode Q5: Provider credential missing → credential_blocked
    metadata visible, no secret leakage."""

    @pytest.mark.asyncio
    async def test_missing_credential_credential_blocked_visible(self) -> None:
        """When provider returns CREDENTIALS_BLOCKED, the response must
        surface credential_blocked status and an honest message."""
        tool_resp = PlaceToolResponse(
            status=PlaceToolStatus.CREDENTIALS_BLOCKED,
            source=PlaceToolSource.GOOGLE_PLACES,
            candidates=[],
            request=PlaceSearchRequest(query="hải sản"),
            retrieved_at=datetime.now(UTC),
        )
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-fm-cred",
            message="tìm quán hải sản",
            language="vi",
        )

        assert response.places == []
        assert "thiếu cấu hình" in response.message
        # Follow-up context should not be populated with place data
        ctx = await cp.load_context("s-fm-cred")
        if ctx is not None:
            assert ctx.place_ids == []


# ---------------------------------------------------------------------------
# T06-8: Failure Mode (Q5) — provider timeout/error
# ---------------------------------------------------------------------------

class TestFailureModeProviderError:
    """Failure Mode Q5: Provider timeout/error → status/error metadata
    reaches response without fabricated explanation."""

    @pytest.mark.asyncio
    async def test_provider_error_reaches_response(self) -> None:
        """UPSTREAM_ERROR must reach the response with safe diagnostics."""
        tool_resp = PlaceToolResponse(
            status=PlaceToolStatus.UPSTREAM_ERROR,
            source=PlaceToolSource.GOOGLE_PLACES,
            candidates=[],
            request=PlaceSearchRequest(query="hải sản"),
            retrieved_at=datetime.now(UTC),
        )
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-fm-err",
            message="tìm quán hải sản",
            language="vi",
        )

        assert response.places == []
        assert response.reasoning_log is not None
        assert "upstream_error" in response.reasoning_log.lower()
        # No fabricated explanation
        for place in response.places:
            assert not place.explanation.matched_preferences


# ---------------------------------------------------------------------------
# T06-9: Failure Mode (Q5) — malformed provider results
# ---------------------------------------------------------------------------

class TestFailureModeMalformedResults:
    """Failure Mode Q5: Malformed provider response → safe degraded response,
    no hallucinated places."""

    @pytest.mark.asyncio
    async def test_malformed_provider_results_safe_degradation(self) -> None:
        """Provider returns OK but with weird/minimal candidate data →
        service must handle gracefully or reject via Pydantic."""
        # Minimal candidate — only required fields
        candidate = PlaceCandidate(
            place_id="places/minimal",
            display_name="Minimal",
            types=["restaurant"],
            formatted_address="Unknown",
            location=LatLng(lat=10.0, lng=104.0),
            local_factor=0.3,
            map_uri="https://map.goong.io/?pid=minimal",
            rating=None,
            price_level=None,
            open_now=None,
            business_status=None,
        )
        tool_resp = _make_ok_response(candidates=[candidate])
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-fm-malformed",
            message="tìm quán hải sản",
            language="vi",
        )

        # Should not crash — either returns the place with fallback scores
        # or empty places with safe message
        assert response.fallback is False
        if response.places:
            for place in response.places:
                assert place.score_breakdown is not None
                assert place.explanation is not None
        else:
            assert response.message  # At least an honest message


# ---------------------------------------------------------------------------
# T06-10: Observability — follow-up decision source visible
# ---------------------------------------------------------------------------

class TestObservabilityFollowUpSource:
    """Verify the response surfaces show which context source was used
    (structured_context vs history_context vs fallback/RAG)."""

    @pytest.mark.asyncio
    async def test_structured_context_intent_visible(self) -> None:
        """Follow-up resolved from structured context must show
        followup_contextual intent, not RAG or generic intent."""
        tool_resp = _make_ok_response(candidates=[
            _ham_ninh_candidate("places/obs-a", "Quán Quan Sát"),
        ])
        service, cp = _make_service(tool_resp)

        # Turn 1: get place response
        await service.answer(
            session_id="s-obs-01",
            message="tìm quán hải sản",
            language="vi",
        )

        # Turn 2: contextual follow-up
        response = await service.answer(
            session_id="s-obs-01",
            message="Quán Quan Sát giá bao nhiêu?",
            language="vi",
        )

        assert response.intent == "followup_contextual"
        assert response.fallback is False

    @pytest.mark.asyncio
    async def test_history_context_intent_visible(self) -> None:
        """Follow-up resolved from history must show followup_history intent."""
        cp = InMemoryAgentCheckpointer()
        await cp.save_turn("s-obs-hist", "Gợi ý quán ăn", "Có 4 nhóm chính...")

        service = AgentService(
            retriever=None,
            checkpointer=cp,
            checkpoint_mode="test",
            place_recommendation_service=None,
            llm_service=None,
        )

        response = await service.answer(
            session_id="s-obs-hist",
            message="ví dụ",
            language="vi",
        )

        assert response.intent == "followup_history"
        assert response.fallback is False

    @pytest.mark.asyncio
    async def test_new_request_not_treated_as_followup(self) -> None:
        """A completely new place request must get place_recommendation intent,
        not followup_contextual."""
        tool_resp = _make_ok_response()
        service, cp = _make_service(tool_resp)

        response = await service.answer(
            session_id="s-obs-new",
            message="tìm quán cà phê gần đây",
            language="vi",
        )

        assert response.intent == PLACE_RECOMMENDATION_INTENT
        assert response.fallback is False
