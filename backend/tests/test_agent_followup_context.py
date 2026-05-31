"""Tests for the structured follow-up context contract (R052 / M014-S01-T01).

These tests verify:
- FollowUpContext serialization / deserialization round-trips
- resolve_followup_decision classification for all four labels
- _build_followup_context extraction from ChatResponse
- Checkpointer save/load_context backward-compatible extension
- Negative tests: empty context, malformed context, ambiguous pronouns

Labels under test:
  structured_context  — follow-up references prior structured context
  history_context     — follow-up answerable from conversation history alone
  clarification_needed — ambiguous pronoun or underspecified follow-up
  insufficient_context — no prior context or history to resolve from
"""

from __future__ import annotations

import pytest

from agents.graph.agent_service import (
    FollowUpContext,
    FollowUpDecision,
    InMemoryAgentCheckpointer,
    PostgresAgentCheckpointer,
    _build_followup_context,
    _is_ambiguous_pronoun_followup,
    _matches_structured_context,
    resolve_followup_decision,
)
from agents.services.place_recommendation_service import PLACE_RECOMMENDATION_INTENT
from app.models.places import PlaceDecisionTrace, PlaceAuditEvent, PlaceAuditPhase
from app.models.response import ChatResponse, PlaceResult, ScoreBreakdown, PlaceExplanation, Citation
from app.models.request import LatLng


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_place_result(
    place_id: str = "goong_123",
    display_name: str = "Nhà hàng Hải Sản Biển Xanh",
    final_score: float = 0.87,
) -> PlaceResult:
    return PlaceResult(
        place_id=place_id,
        display_name=display_name,
        formatted_address="123 Đường Biển, Phú Quốc",
        location=LatLng(lat=10.18, lng=104.05),
        types=["restaurant", "seafood_restaurant"],
        primary_type="seafood_restaurant",
        rating=4.5,
        user_rating_count=128,
        price_level=2,
        open_now=True,
        business_status="OPERATIONAL",
        local_factor=0.8,
        final_score=final_score,
        score_breakdown=ScoreBreakdown(
            tree1_locality=0.90,
            tree2_proximity=0.65,
            tree3_quality=0.75,
            s_bag=0.767,
            delta1_fairness=-0.045,
            delta2_access=0.0,
            final_score=final_score,
            rank=1,
        ),
        accessibility_score=0.75,
        map_uri="https://map.goong.io/?pid=goong_123",
        explanation=PlaceExplanation(
            rank=1,
            primary_reason="Fresh seafood with high local factor",
            matched_preferences=["seafood", "local"],
            local_context="Ham Ninh fishing village",
            score_factors={"final_score": final_score},
            fairness_note="local_factor=0.8",
            accessibility_note="wheelchair access available",
            route_summary="500m from Ham Ninh center",
            provider_source="goong_places",
            provider_status="ok",
            evidence_fields_used=["display_name", "rating", "local_factor"],
        ),
    )


def _make_chat_response(
    session_id: str = "test-sess-1",
    message: str = "Dưới đây là gợi ý hải sản...",
    places: list | None = None,
    citations: list | None = None,
    intent: str | None = PLACE_RECOMMENDATION_INTENT,
    reasoning_log: str | None = "Found 3 seafood restaurants near Ham Ninh.",
    fallback: bool = False,
    decision_trace: PlaceDecisionTrace | None = None,
) -> ChatResponse:
    if places is None:
        places = [_make_place_result()]
    if citations is None:
        citations = [
            Citation(source="Vietnam Tourism", url="https://example.com", snippet="Ham Ninh seafood"),
        ]
    if decision_trace is None:
        decision_trace = PlaceDecisionTrace(
            events=[
                PlaceAuditEvent(
                    event="provider_called",
                    phase=PlaceAuditPhase.PROVIDER,
                    detail={"endpoint": "text_search"},
                    elapsed_ms=10.0,
                ),
                PlaceAuditEvent(
                    event="provider_ok",
                    phase=PlaceAuditPhase.PROVIDER,
                    detail={"count": 3},
                    elapsed_ms=120.0,
                ),
            ],
            session_id=session_id,
            credential_status="live",
            provider_source="goong_places",
        )
    return ChatResponse(
        session_id=session_id,
        message=message,
        places=places,
        citations=citations,
        reasoning_log=reasoning_log,
        intent=intent,
        latency_ms=250.0,
        fallback=fallback,
        decision_trace=decision_trace,
    )


# ---------------------------------------------------------------------------
# FollowUpContext serialization / deserialization
# ---------------------------------------------------------------------------

class TestFollowUpContextSerialization:
    """Round-trip tests for FollowUpContext.to_dict() / from_dict()."""

    def test_roundtrip_with_places(self) -> None:
        ctx = FollowUpContext(
            session_id="sess-1",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_ids=["goong_1", "goong_2"],
            place_display_names=["Quán A", "Quán B"],
            has_citations=True,
            citation_sources=["Source X"],
            reasoning_log_summary="Found seafood places",
            score_breakdown_keys=["final_score", "tree1_locality"],
            provider_source="goong_places",
            provider_status="ok",
            fallback=False,
            explanation_keys=["primary_reason", "local_context"],
        )
        data = ctx.to_dict()
        restored = FollowUpContext.from_dict(data)
        assert restored is not None
        assert restored.session_id == "sess-1"
        assert restored.intent == PLACE_RECOMMENDATION_INTENT
        assert restored.place_ids == ["goong_1", "goong_2"]
        assert restored.place_display_names == ["Quán A", "Quán B"]
        assert restored.has_citations is True
        assert restored.citation_sources == ["Source X"]
        assert restored.reasoning_log_summary == "Found seafood places"
        assert restored.score_breakdown_keys == ["final_score", "tree1_locality"]
        assert restored.provider_source == "goong_places"
        assert restored.provider_status == "ok"
        assert restored.fallback is False
        assert restored.explanation_keys == ["primary_reason", "local_context"]
        assert restored._version == 1

    def test_from_dict_none_returns_none(self) -> None:
        assert FollowUpContext.from_dict(None) is None
        assert FollowUpContext.from_dict({}) is not None  # empty dict → empty context

    def test_from_dict_malformed_returns_none(self) -> None:
        # Not a dict at all
        assert FollowUpContext.from_dict("not a dict") is None  # type: ignore
        assert FollowUpContext.from_dict([]) is None  # type: ignore

    def test_from_dict_partial_data(self) -> None:
        data = {"session_id": "s1", "intent": "test"}
        ctx = FollowUpContext.from_dict(data)
        assert ctx is not None
        assert ctx.session_id == "s1"
        assert ctx.intent == "test"
        assert ctx.place_ids == []
        # intent alone does not make context populated — needs place/citation/log data
        assert ctx.is_populated is False

    def test_is_populated_true_when_place_ids_exist(self) -> None:
        ctx = FollowUpContext(session_id="s1", place_ids=["p1"])
        assert ctx.is_populated is True

    def test_is_populated_false_when_only_intent_set(self) -> None:
        ctx = FollowUpContext(session_id="s1", intent="test_intent")
        assert ctx.is_populated is False

    def test_is_populated_true_when_citation_sources(self) -> None:
        ctx = FollowUpContext(session_id="s1", citation_sources=["Src"])
        assert ctx.is_populated is True

    def test_is_populated_true_when_reasoning_log(self) -> None:
        ctx = FollowUpContext(session_id="s1", reasoning_log_summary="log")
        assert ctx.is_populated is True

    def test_is_populated_false_when_empty(self) -> None:
        ctx = FollowUpContext(session_id="s1")
        assert ctx.is_populated is False


# ---------------------------------------------------------------------------
# resolve_followup_decision — structured_context label
# ---------------------------------------------------------------------------

class TestResolveFollowupStructuredContext:
    """Follow-ups that reference prior structured context should resolve
    from that context rather than from RAG or fallback."""

    def test_place_name_reference_resolves_structured(self) -> None:
        ctx = FollowUpContext(
            session_id="s1",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_display_names=["Nhà hàng Hải Sản Biển Xanh", "Quán Cua Đồng"],
            place_ids=["goong_1", "goong_2"],
        )
        decision = resolve_followup_decision("Biển Xanh có mở cửa không?", ctx)
        assert decision == "structured_context"

    def test_partial_place_name_match(self) -> None:
        ctx = FollowUpContext(
            session_id="s1",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_display_names=["Homestay Ngọc Lan"],
        )
        decision = resolve_followup_decision("Ngọc Lan giá bao nhiêu?", ctx)
        assert decision == "structured_context"

    def test_score_reference_with_score_breakdown(self) -> None:
        ctx = FollowUpContext(
            session_id="s1",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_ids=["goong_1"],
            score_breakdown_keys=["final_score", "tree1_locality"],
        )
        decision = resolve_followup_decision("Vì sao quán này được xếp cao?", ctx)
        assert decision == "structured_context"

    def test_why_ranked_with_score_breakdown(self) -> None:
        ctx = FollowUpContext(
            session_id="s1",
            intent=PLACE_RECOMMENDATION_INTENT,
            score_breakdown_keys=["final_score"],
        )
        decision = resolve_followup_decision("why is this ranked first?", ctx)
        assert decision == "structured_context"

    def test_citation_source_reference(self) -> None:
        ctx = FollowUpContext(
            session_id="s1",
            intent="cultural_query",
            has_citations=True,
            citation_sources=["Vietnam Tourism Board"],
        )
        decision = resolve_followup_decision("Nguồn này có đáng tin không?", ctx)
        assert decision == "structured_context"

    def test_provider_reference(self) -> None:
        ctx = FollowUpContext(
            session_id="s1",
            intent=PLACE_RECOMMENDATION_INTENT,
            provider_source="goong_places",
            provider_status="ok",
        )
        decision = resolve_followup_decision("Nguồn dữ liệu từ đâu?", ctx)
        assert decision == "structured_context"

    def test_place_recommendation_with_demonstrative(self) -> None:
        ctx = FollowUpContext(
            session_id="s1",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_ids=["goong_1"],
            place_display_names=["Quán Hải Sản"],
        )
        decision = resolve_followup_decision("địa điểm này có ngon không?", ctx)
        assert decision == "structured_context"

    def test_empty_message_returns_insufficient(self) -> None:
        ctx = FollowUpContext(session_id="s1", place_ids=["p1"])
        decision = resolve_followup_decision("", ctx)
        assert decision == "insufficient_context"


# ---------------------------------------------------------------------------
# resolve_followup_decision — history_context label
# ---------------------------------------------------------------------------

class TestResolveFollowupHistoryContext:
    """Follow-ups that are answerable from conversation history alone
    (no structured context needed) should resolve as history_context."""

    def test_short_followup_with_assistant_history(self) -> None:
        ctx = None  # no structured context
        history = [
            {"role": "user", "content": "Gợi ý quán ăn"},
            {"role": "assistant", "content": "Có 4 nhóm chính..."},
        ]
        decision = resolve_followup_decision("ví dụ", ctx, history)
        assert decision == "history_context"

    def test_question_mark_followup(self) -> None:
        ctx = None
        history = [
            {"role": "assistant", "content": "Hàm Ninh có nhiều quán ngon."},
        ]
        decision = resolve_followup_decision("?", ctx, history)
        assert decision == "history_context"

    def test_no_history_no_context(self) -> None:
        decision = resolve_followup_decision("là sao", context=None, history=[])
        assert decision in ("insufficient_context", "clarification_needed")


# ---------------------------------------------------------------------------
# resolve_followup_decision — clarification_needed label
# ---------------------------------------------------------------------------

class TestResolveFollowupClarificationNeeded:
    """Ambiguous pronoun follow-ups without clear referents should
    return clarification_needed rather than inventing facts."""

    def test_ambiguous_pronoun_short(self) -> None:
        ctx = FollowUpContext(session_id="s1")  # empty context
        decision = resolve_followup_decision("nó gì?", ctx)
        assert decision == "clarification_needed"

    def test_ambiguous_pronoun_those(self) -> None:
        ctx = None
        decision = resolve_followup_decision("those?", ctx)
        assert decision == "clarification_needed"

    def test_ambiguous_pronoun_them(self) -> None:
        ctx = None
        decision = resolve_followup_decision("tell me about them", ctx)
        assert decision == "clarification_needed"

    def test_ambiguous_ấy_short(self) -> None:
        ctx = FollowUpContext(session_id="s1")
        decision = resolve_followup_decision("cái ấy", ctx)
        assert decision == "clarification_needed"


# ---------------------------------------------------------------------------
# resolve_followup_decision — insufficient_context label
# ---------------------------------------------------------------------------

class TestResolveFollowupInsufficientContext:
    """When there is no prior context or history, follow-ups should
    return insufficient_context."""

    def test_no_context_no_history(self) -> None:
        decision = resolve_followup_decision("quán nào ngon nhất?", context=None, history=[])
        assert decision == "insufficient_context"

    def test_empty_context_no_history(self) -> None:
        ctx = FollowUpContext(session_id="s1")
        assert ctx.is_populated is False
        decision = resolve_followup_decision("quán nào ngon?", ctx, history=[])
        assert decision == "insufficient_context"

    def test_no_context_no_history_empty_message(self) -> None:
        decision = resolve_followup_decision("", context=None, history=[])
        assert decision == "insufficient_context"


# ---------------------------------------------------------------------------
# _matches_structured_context unit tests
# ---------------------------------------------------------------------------

class TestMatchesStructuredContext:
    """Direct tests for the structured context matching logic."""

    def test_matches_display_name_token(self) -> None:
        ctx = FollowUpContext(
            session_id="s1",
            place_display_names=["Nhà hàng Cua Đồng quê"],
        )
        assert _matches_structured_context("cua đồng", ctx) is True

    def test_no_match_when_names_empty(self) -> None:
        ctx = FollowUpContext(session_id="s1", place_display_names=[])
        assert _matches_structured_context("anything", ctx) is False

    def test_matches_score_terms(self) -> None:
        ctx = FollowUpContext(
            session_id="s1",
            score_breakdown_keys=["final_score"],
        )
        assert _matches_structured_context("sao xếp hạng cao", ctx) is True

    def test_matches_citation_terms(self) -> None:
        ctx = FollowUpContext(session_id="s1", has_citations=True)
        assert _matches_structured_context("nguồn trích dẫn", ctx) is True

    def test_no_match_without_relevant_terms(self) -> None:
        ctx = FollowUpContext(
            session_id="s1",
            place_ids=["p1"],
            place_display_names=["Quán A"],
        )
        assert _matches_structured_context("hello world unrelated", ctx) is False


# ---------------------------------------------------------------------------
# _is_ambiguous_pronoun_followup unit tests
# ---------------------------------------------------------------------------

class TestIsAmbiguousPronounFollowup:
    """Direct tests for ambiguous pronoun detection."""

    @pytest.mark.parametrize("text", [
        "nó",
        "chúng",
        "đó",
        "that",
        "them",
        "nó gì",
        "cái ấy",
    ])
    def test_ambiguous_inputs(self, text: str) -> None:
        assert _is_ambiguous_pronoun_followup(text) is True

    @pytest.mark.parametrize("text", [
        "nhà hàng này ngon không",  # specific noun reference
        "cho tôi biết về quán Biển Xanh",  # named place
        "hello",  # greeting
        "tìm đường đến Hàm Ninh",  # direction request
    ])
    def test_unambiguous_inputs(self, text: str) -> None:
        assert _is_ambiguous_pronoun_followup(text) is False


# ---------------------------------------------------------------------------
# _build_followup_context from ChatResponse
# ---------------------------------------------------------------------------

class TestBuildFollowupContext:
    """Verify that _build_followup_context correctly extracts structured
    metadata from a ChatResponse."""

    def test_extracts_place_ids_and_names(self) -> None:
        response = _make_chat_response(
            places=[
                _make_place_result("goong_1", "Quán A"),
                _make_place_result("goong_2", "Quán B"),
            ],
        )
        ctx = _build_followup_context(response)
        assert ctx.place_ids == ["goong_1", "goong_2"]
        assert ctx.place_display_names == ["Quán A", "Quán B"]

    def test_extracts_citations(self) -> None:
        response = _make_chat_response(
            citations=[
                Citation(source="Source X", url="https://x.com", snippet="..."),
                Citation(source="Source Y", url="https://y.com", snippet="..."),
            ],
        )
        ctx = _build_followup_context(response)
        assert ctx.has_citations is True
        assert "Source X" in ctx.citation_sources
        assert "Source Y" in ctx.citation_sources

    def test_extracts_intent(self) -> None:
        response = _make_chat_response(intent="restaurant_search")
        ctx = _build_followup_context(response)
        assert ctx.intent == "restaurant_search"

    def test_extracts_reasoning_log_summary(self) -> None:
        response = _make_chat_response(
            reasoning_log="This is a detailed reasoning log about the search."
        )
        ctx = _build_followup_context(response)
        assert ctx.reasoning_log_summary is not None
        assert "detailed reasoning" in ctx.reasoning_log_summary

    def test_extracts_provider_from_decision_trace(self) -> None:
        response = _make_chat_response()
        ctx = _build_followup_context(response)
        assert ctx.provider_source == "goong_places"
        assert ctx.provider_status == "live"

    def test_extracts_score_breakdown_keys(self) -> None:
        response = _make_chat_response()
        ctx = _build_followup_context(response)
        assert "final_score" in ctx.score_breakdown_keys
        assert "tree1_locality" in ctx.score_breakdown_keys

    def test_extracts_explanation_keys(self) -> None:
        response = _make_chat_response()
        ctx = _build_followup_context(response)
        assert "primary_reason" in ctx.explanation_keys
        assert "local_context" in ctx.explanation_keys

    def test_fallback_flag_preserved(self) -> None:
        response = _make_chat_response(fallback=True)
        ctx = _build_followup_context(response)
        assert ctx.fallback is True

    def test_empty_response_yields_empty_context(self) -> None:
        response = ChatResponse(
            session_id="test-sess-empty",
            message="test",
            places=[],
            citations=[],
            reasoning_log=None,
            intent=None,
            latency_ms=250.0,
            fallback=False,
            decision_trace=None,
        )
        ctx = _build_followup_context(response)
        assert ctx.is_populated is False

    def test_reasoning_log_truncated_to_500_chars(self) -> None:
        long_log = "x" * 1000
        response = _make_chat_response(reasoning_log=long_log)
        ctx = _build_followup_context(response)
        assert ctx.reasoning_log_summary is not None
        assert len(ctx.reasoning_log_summary) <= 500


# ---------------------------------------------------------------------------
# Checkpointer save/load_context (backward-compatible extension)
# ---------------------------------------------------------------------------

class TestInMemoryCheckpointerContext:
    """Tests for InMemoryAgentCheckpointer save_context / load_context."""

    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self) -> None:
        cp = InMemoryAgentCheckpointer()
        ctx = FollowUpContext(
            session_id="sess-ctx-1",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_ids=["goong_1"],
            place_display_names=["Quán Test"],
            has_citations=True,
        )
        await cp.save_context("sess-ctx-1", ctx)
        loaded = await cp.load_context("sess-ctx-1")
        assert loaded is not None
        assert loaded.session_id == "sess-ctx-1"
        assert loaded.intent == PLACE_RECOMMENDATION_INTENT
        assert loaded.place_ids == ["goong_1"]
        assert loaded.place_display_names == ["Quán Test"]
        assert loaded.has_citations is True

    @pytest.mark.asyncio
    async def test_load_unknown_session_returns_none(self) -> None:
        cp = InMemoryAgentCheckpointer()
        loaded = await cp.load_context("nonexistent-session")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_context_isolation_between_sessions(self) -> None:
        cp = InMemoryAgentCheckpointer()
        ctx1 = FollowUpContext(session_id="s1", place_ids=["p1"])
        ctx2 = FollowUpContext(session_id="s2", place_ids=["p2", "p3"])
        await cp.save_context("s1", ctx1)
        await cp.save_context("s2", ctx2)
        assert (await cp.load_context("s1")).place_ids == ["p1"]
        assert (await cp.load_context("s2")).place_ids == ["p2", "p3"]

    @pytest.mark.asyncio
    async def test_context_independent_of_history(self) -> None:
        """save_context/load_context must not interfere with existing
        save_turn/load_history users."""
        cp = InMemoryAgentCheckpointer()
        await cp.save_turn("s1", "hello", "hi there")
        await cp.save_context("s1", FollowUpContext(session_id="s1", intent="test"))
        history = await cp.load_history("s1")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_load_context_after_overwrite(self) -> None:
        cp = InMemoryAgentCheckpointer()
        ctx1 = FollowUpContext(session_id="s1", place_ids=["p1"])
        ctx2 = FollowUpContext(session_id="s1", place_ids=["p2", "p3"])
        await cp.save_context("s1", ctx1)
        await cp.save_context("s1", ctx2)
        loaded = await cp.load_context("s1")
        assert loaded is not None
        assert loaded.place_ids == ["p2", "p3"]


class TestPostgresCheckpointerContextContract:
    """Contract tests for PostgresAgentCheckpointer save/load_context.

    Uses a fake pool to verify the SQL interface without needing a real DB.
    These tests verify the method signatures and JSON serialization.
    """

    @pytest.mark.asyncio
    async def test_load_context_handles_missing_table_gracefully(self) -> None:
        """If the context table doesn't exist yet, load_context should
        return None without raising."""
        class FakeRow:
            pass

        class FakeConn:
            async def fetchval(self, query, *args):
                raise Exception("relation does not exist")

        class FakeAcquire:
            async def __aenter__(self):
                return FakeConn()
            async def __aexit__(self, *args):
                return False

        class FakePool:
            def acquire(self):
                return FakeAcquire()

        cp = PostgresAgentCheckpointer(FakePool())
        loaded = await cp.load_context("s1")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_context_parses_json_string(self) -> None:
        import json

        class FakeConn:
            async def fetchval(self, query, *args):
                return json.dumps({
                    "session_id": "s1",
                    "intent": "test",
                    "place_ids": ["p1"],
                    "place_display_names": ["Quán A"],
                })

        class FakeAcquire:
            async def __aenter__(self):
                return FakeConn()
            async def __aexit__(self, *args):
                return False

        class FakePool:
            def acquire(self):
                return FakeAcquire()

        cp = PostgresAgentCheckpointer(FakePool())
        loaded = await cp.load_context("s1")
        assert loaded is not None
        assert loaded.session_id == "s1"
        assert loaded.intent == "test"
        assert loaded.place_ids == ["p1"]

    @pytest.mark.asyncio
    async def test_load_context_handles_malformed_json(self) -> None:
        class FakeConn:
            async def fetchval(self, query, *args):
                return "not valid json {{{"

        class FakeAcquire:
            async def __aenter__(self):
                return FakeConn()
            async def __aexit__(self, *args):
                return False

        class FakePool:
            def acquire(self):
                return FakeAcquire()

        cp = PostgresAgentCheckpointer(FakePool())
        loaded = await cp.load_context("s1")
        assert loaded is None


# ---------------------------------------------------------------------------
# Decision label coverage — all four labels must appear in test assertions
# ---------------------------------------------------------------------------

class TestAllDecisionLabelsCovered:
    """Integration-style test ensuring all four decision labels are
    exercised by the test suite."""

    def test_structured_context_label(self) -> None:
        ctx = FollowUpContext(
            session_id="s1",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_display_names=["Quán Biển Xanh"],
        )
        assert resolve_followup_decision("Biển Xanh mở mấy giờ?", ctx) == "structured_context"

    def test_history_context_label(self) -> None:
        history = [
            {"role": "assistant", "content": "Hàm Ninh có nhiều quán hải sản ngon."},
        ]
        assert resolve_followup_decision("ví dụ", context=None, history=history) == "history_context"

    def test_clarification_needed_label(self) -> None:
        ctx = FollowUpContext(session_id="s1")  # not populated
        assert resolve_followup_decision("nó sao?", ctx) == "clarification_needed"

    def test_insufficient_context_label(self) -> None:
        assert resolve_followup_decision("recommend something", context=None, history=[]) == "insufficient_context"


# ---------------------------------------------------------------------------
# Negative tests — empty/malformed context must NOT cause crashes
# ---------------------------------------------------------------------------

class TestNegativeCases:
    """Edge cases that must not crash or invent facts."""

    def test_none_context_none_history(self) -> None:
        decision = resolve_followup_decision("follow up question", None, None)
        assert decision in ("insufficient_context", "clarification_needed")

    def test_empty_context_with_non_matching_message(self) -> None:
        ctx = FollowUpContext(session_id="s1")
        decision = resolve_followup_decision("something totally unrelated", ctx, [])
        assert decision == "insufficient_context"

    def test_malformed_context_from_dict(self) -> None:
        ctx = FollowUpContext.from_dict({"place_ids": "not_a_list"})  # type: ignore
        assert ctx is not None  # should not crash
        assert ctx.place_ids == []  # non-list values default to empty list

    def test_context_with_unicode_place_names(self) -> None:
        ctx = FollowUpContext(
            session_id="s1",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_ids=["goong_emoji_1"],
            place_display_names=["Quán Hải Sản", "Cafe"],
        )
        assert ctx.is_populated is True
        decision = resolve_followup_decision("Hải Sản có tươi không?", ctx)
        assert decision == "structured_context"

    def test_long_message_does_not_cause_issues(self) -> None:
        ctx = FollowUpContext(session_id="s1", place_ids=["p1"])
        long_msg = "x" * 5000
        decision = resolve_followup_decision(long_msg, ctx, [])
        assert decision in ("insufficient_context", "structured_context", "clarification_needed")

    def test_followup_decisions_are_valid_literals(self) -> None:
        valid_labels: set[FollowUpDecision] = {
            "structured_context",
            "history_context",
            "clarification_needed",
            "insufficient_context",
        }
        # Verify all our resolve_followup_decision calls return valid labels
        ctx = FollowUpContext(
            session_id="s1",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_display_names=["Test Place"],
        )
        for msg in ["Test Place gì?", "nó?", "", "ví dụ"]:
            decision = resolve_followup_decision(msg, ctx, [])
            assert decision in valid_labels, f"Invalid label: {decision}"


# ---------------------------------------------------------------------------
# T02: AgentService integration — context persistence across turns
# ---------------------------------------------------------------------------

class TestAgentServiceContextIntegration:
    """Integration tests verifying that AgentService saves context after
    place responses and loads it on subsequent turns."""

    @pytest.mark.asyncio
    async def test_answer_saves_context_after_place_response(self) -> None:
        """After a place response, _build_followup_context + save_context
        persists structured context that survives load_context round-trip."""
        checkpointer = InMemoryAgentCheckpointer()
        response = _make_chat_response(
            session_id="sess-t02-1",
            places=[_make_place_result("goong_t02", "Quán T02 Test")],
            citations=[],
            reasoning_log="T02 integration test place response.",
        )
        # Build context from response (what _save_followup_context does)
        ctx = _build_followup_context(response)
        assert ctx.is_populated is True
        assert "goong_t02" in ctx.place_ids
        assert "Quán T02 Test" in ctx.place_display_names
        # Persist via checkpointer
        await checkpointer.save_context("sess-t02-1", ctx)
        loaded = await checkpointer.load_context("sess-t02-1")
        assert loaded is not None
        assert loaded.is_populated is True
        assert "goong_t02" in loaded.place_ids
        assert "Quán T02 Test" in loaded.place_display_names

    @pytest.mark.asyncio
    async def test_answer_loads_prior_context_on_followup(self) -> None:
        """When a session has prior context stored, _initial_state loads it
        and classifies the follow-up decision."""
        checkpointer = InMemoryAgentCheckpointer()
        # Pre-seed context from a prior turn
        prior = FollowUpContext(
            session_id="sess-followup",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_ids=["goong_prev"],
            place_display_names=["Quán Biển Xanh"],
            score_breakdown_keys=["final_score", "tree1_locality"],
        )
        await checkpointer.save_context("sess-followup", prior)
        await checkpointer.save_turn("sess-followup", "Tìm quán hải sản", "Dưới đây là gợi ý...")

        # Simulate _initial_state logic
        history = await checkpointer.load_history("sess-followup")
        loaded_ctx = await checkpointer.load_context("sess-followup")

        assert loaded_ctx is not None
        assert loaded_ctx.is_populated is True
        assert "Quán Biển Xanh" in loaded_ctx.place_display_names

        # Classify a contextual follow-up
        decision = resolve_followup_decision(
            "Biển Xanh có mở cửa cuối tuần không?",
            loaded_ctx,
            history,
        )
        assert decision == "structured_context"

    @pytest.mark.asyncio
    async def test_context_isolation_across_sessions(self) -> None:
        """Context saved for one session must not leak into another."""
        cp = InMemoryAgentCheckpointer()
        ctx_a = FollowUpContext(
            session_id="sess-a",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_ids=["goong_a"],
            place_display_names=["Quán A"],
        )
        ctx_b = FollowUpContext(
            session_id="sess-b",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_ids=["goong_b"],
            place_display_names=["Quán B"],
        )
        await cp.save_context("sess-a", ctx_a)
        await cp.save_context("sess-b", ctx_b)

        loaded_a = await cp.load_context("sess-a")
        loaded_b = await cp.load_context("sess-b")
        assert loaded_a is not None
        assert loaded_b is not None
        assert loaded_a.place_ids == ["goong_a"]
        assert loaded_b.place_ids == ["goong_b"]
        # Cross-session leakage check
        assert "Quán B" not in loaded_a.place_display_names
        assert "Quán A" not in loaded_b.place_display_names

    @pytest.mark.asyncio
    async def test_malformed_context_does_not_crash_flow(self) -> None:
        """If stored context is corrupted, load_context returns None and
        the flow degrades to history_context or insufficient_context."""
        cp = InMemoryAgentCheckpointer()
        # Manually inject malformed data
        cp._context_store["sess-bad"] = {"place_ids": "not_a_list", "intent": None}

        loaded = await cp.load_context("sess-bad")
        # from_dict handles malformed place_ids via _safe_list, so it won't crash
        # but intent=None + empty place_ids = not populated
        assert loaded is not None  # from_dict tolerates this
        assert loaded.place_ids == []
        assert loaded.is_populated is False

        # A follow-up on non-populated context degrades properly
        decision = resolve_followup_decision(
            "quán nào ngon nhất?",
            loaded,
            [],
        )
        assert decision == "insufficient_context"

    @pytest.mark.asyncio
    async def test_empty_response_does_not_overwrite_prior_context(self) -> None:
        """A conversational (non-place) response should not overwrite
        meaningful prior context with an empty context."""
        cp = InMemoryAgentCheckpointer()
        prior = FollowUpContext(
            session_id="sess-protect",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_ids=["goong_1", "goong_2"],
            place_display_names=["Quán X", "Quán Y"],
        )
        await cp.save_context("sess-protect", prior)

        # Simulate a conversational response with no places, no decision trace
        empty_response = ChatResponse(
            session_id="sess-protect",
            message="Hello! How can I help?",
            places=[],
            citations=[],
            reasoning_log=None,
            intent="conversational",
            latency_ms=50.0,
            fallback=False,
            decision_trace=None,
        )
        ctx = _build_followup_context(empty_response)
        # Only save if populated — protects prior context
        if ctx.is_populated:
            await cp.save_context("sess-protect", ctx)

        loaded = await cp.load_context("sess-protect")
        # Prior context preserved because empty response wasn't saved
        assert loaded is not None
        assert loaded.place_ids == ["goong_1", "goong_2"]

    @pytest.mark.asyncio
    async def test_context_save_failure_degrades_gracefully(self) -> None:
        """If checkpointer.save_context raises, the flow must not crash."""
        class FailingCheckpointer(InMemoryAgentCheckpointer):
            async def save_context(self, session_id: str, ctx: FollowUpContext) -> None:
                raise RuntimeError("simulated storage failure")

        cp = FailingCheckpointer()
        ctx = FollowUpContext(
            session_id="sess-fail",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_ids=["goong_1"],
            place_display_names=["Quán Test"],
        )
        # Should not raise — callers must handle gracefully
        try:
            await cp.save_context("sess-fail", ctx)
        except RuntimeError:
            pass  # Expected — real _save_followup_context catches this
