"""Chat transport for the single HamNinhGraph runtime."""

from __future__ import annotations

import datetime
import json
import time
from collections.abc import AsyncGenerator
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.middleware.rate_limiter import get_limiter
from app.models.request import ChatRequest
from app.models.response import ChatResponse

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/chat")
limiter = get_limiter()
chat_rate_limit = get_settings().RATE_LIMIT_CHAT
FEEDBACK_LOG_PATH = Path("/tmp/chat_feedback.jsonl")


class FeedbackRequest(BaseModel):
    message_id: str
    feedback_type: str
    reason: str | None = None
    session_id: str | None = None
    turn_index: int | None = None
    message_content: str | None = None


class ResumeRequest(BaseModel):
    session_id: str
    resume_value: dict = Field(description="JSON value returned from the pending interrupt")


def _graph(request: Request):
    graph = getattr(request.app.state, "ham_ninh_graph", None)
    if graph is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "service_unavailable",
                "message": "The agent graph is not available.",
            },
        )
    return graph


def _chat_response(session_id: str, graph_result, started: float) -> ChatResponse:
    return ChatResponse(
        session_id=session_id,
        message=graph_result.response_text or "Mình chưa thể tạo câu trả lời.",
        intent=graph_result.intent or "unknown",
        citations=graph_result.citations or [],
        places=graph_result.places or [],
        suggestions=graph_result.suggestions or [],
        reasoning_log=graph_result.reasoning_log,
        fallback=graph_result.blocked,
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
        langfuse_trace_id=graph_result.langfuse_trace_id,
    )


def _sse_payload(value: str) -> str:
    lines = str(value).splitlines() or [""]
    return "".join(f"data: {line}\n" for line in lines) + "\n"


def _streaming_response(generator: AsyncGenerator[str, None]) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _error_stream(error_type: str, message: str, retryable: bool) -> StreamingResponse:
    async def events() -> AsyncGenerator[str, None]:
        payload = {
            "type": error_type,
            "message": message,
            "retryable": retryable,
            "next_action": "retry" if retryable else "check_service",
        }
        yield _sse_payload("[STATUS] failed-recoverable" if retryable else "[STATUS] failed-terminal")
        yield _sse_payload(f"[ERROR] {json.dumps(payload, ensure_ascii=False)}")
        yield _sse_payload("[DONE]")

    return _streaming_response(events())


@router.post("/feedback")
async def submit_feedback(feedback: FeedbackRequest) -> dict[str, str]:
    data = {
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        "message_id": feedback.message_id,
        "feedback_type": feedback.feedback_type,
        "reason": feedback.reason,
        "session_id": feedback.session_id,
        "turn_index": feedback.turn_index,
        "message_content": feedback.message_content[:200] if feedback.message_content else None,
    }
    try:
        FEEDBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with FEEDBACK_LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(json.dumps(data, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.error("feedback.log_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to log feedback") from exc
    return {"status": "ok", "message_id": feedback.message_id}


@router.post("/resume", response_model=ChatResponse)
async def resume_graph(body: ResumeRequest, request: Request) -> ChatResponse:
    started = time.perf_counter()
    try:
        result = await _graph(request).resume(
            session_id=body.session_id,
            resume_value=body.resume_value,
        )
        return _chat_response(body.session_id, result, started)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("chat.resume_failed", session_id=body.session_id)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "resume_failed",
                "message": str(exc),
                "retryable": True,
            },
        ) from exc


@router.post("", response_model=ChatResponse)
@limiter.limit(chat_rate_limit)
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    started = time.perf_counter()
    try:
        user_location = None
        if body.user_location is not None:
            user_location = {
                "lat": body.user_location.lat,
                "lng": body.user_location.lng,
            }
        result = await _graph(request).answer(
            session_id=body.session_id,
            message=body.message,
            language=body.language,
            user_location=user_location,
            budget_filter=body.budget_filter,
            accessibility_required=body.accessibility_required,
        )
        return _chat_response(body.session_id, result, started)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("chat.graph_failed", session_id=body.session_id)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "agent_failed",
                "message": str(exc),
                "retryable": True,
            },
        ) from exc


@router.get("/stream")
@limiter.limit(chat_rate_limit)
async def chat_stream(
    request: Request,
    message: str = Query(...),
    session_id: str = Query(...),
    language: str = Query("vi"),
    lat: float | None = Query(None),
    lng: float | None = Query(None),
    budget: str | None = Query(None),
    accessibility: bool = Query(False),
) -> StreamingResponse:
    query = message.strip()
    sid = session_id.strip()
    if not query or not sid:
        return _error_stream("invalid_request", "Message and session_id are required.", False)

    try:
        graph = _graph(request)
    except HTTPException:
        return _error_stream("service_unavailable", "The agent graph is not available.", True)

    user_location = {"lat": lat, "lng": lng} if lat is not None and lng is not None else None

    async def events() -> AsyncGenerator[str, None]:
        try:
            async for marker in graph.stream_sse(
                session_id=sid,
                message=query,
                language=language,
                user_location=user_location,
                budget_filter=budget,
                accessibility_required=accessibility,
            ):
                yield _sse_payload(marker)
        except Exception as exc:
            logger.exception("chat.stream_failed", session_id=sid)
            payload = {
                "type": type(exc).__name__,
                "message": "Agent execution failed. It is safe to retry.",
                "retryable": True,
                "next_action": "retry",
            }
            yield _sse_payload("[STATUS] failed-recoverable")
            yield _sse_payload(f"[ERROR] {json.dumps(payload)}")
        yield _sse_payload("[DONE]")

    return _streaming_response(events())
