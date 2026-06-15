"""Behavior tests for graph-result to HTTP-response mapping."""

import time

from agents.graph.ham_ninh_graph import GraphResult
from app.routers.chat import _chat_response


def test_chat_response_preserves_public_graph_receipts():
    result = GraphResult(
        response_text="Grounded answer",
        intent="cultural_query",
        suggestions=["More"],
        reasoning_log="retrieval:success",
        langfuse_trace_id="trace-123",
    )

    response = _chat_response("session-123", result, time.perf_counter())

    assert response.session_id == "session-123"
    assert response.message == "Grounded answer"
    assert response.intent == "cultural_query"
    assert response.suggestions == ["More"]
    assert response.reasoning_log == "retrieval:success"
    assert response.langfuse_trace_id == "trace-123"


def test_chat_response_marks_blocked_graph_result_as_fallback():
    response = _chat_response(
        "blocked-session",
        GraphResult(response_text="Blocked", intent="blocked", blocked=True),
        time.perf_counter(),
    )

    assert response.fallback is True
