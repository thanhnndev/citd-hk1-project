"""Chat endpoints - primary user-facing API for the assistant.

Routes both POST and SSE chat transports through the shared AgentService while
preserving the established response and stream wire contracts.
"""

import time
from collections.abc import AsyncGenerator

import structlog
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.middleware.rate_limiter import get_limiter
from app.models.request import ChatRequest
from app.models.response import ChatResponse

# Guardrails — input screening and output grounding
try:
    from agents.guardrails.input_guardrails import (
        block_injection,
        reject_off_topic,
    )
    from agents.guardrails.output_guardrails import verify_grounding
    _GUARDRAILS_AVAILABLE = True
except Exception:
    _GUARDRAILS_AVAILABLE = False

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/chat")
limiter = get_limiter()



def _error_stream(reason: str) -> StreamingResponse:
    async def event_generator() -> AsyncGenerator[str, None]:
        yield f"data: [ERROR] {reason}\n\n"
        yield "data: [DONE]\n\n"

    return _streaming_response(event_generator())


def _sse_payload(value: str) -> str:
    return f"data: {value}\n\n"


def _streaming_response(generator: AsyncGenerator[str, None]) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _agent_service_available(request: Request) -> bool:
    """Preserve legacy unavailable behavior when startup loaded no corpus."""
    return (
        getattr(request.app.state, "agent_service", None) is not None
        and (
            getattr(request.app.state, "retriever", None) is not None
            or getattr(request.app.state, "hybrid_retriever", None) is not None
        )
    )

@router.post("", response_model=ChatResponse)
@limiter.limit("20/minute")
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    """Answer a user query through the shared agent service."""
    t0 = time.perf_counter()
    agent_service = getattr(request.app.state, "agent_service", None)

    if not _agent_service_available(request):
        logger.error("chat.agent_unavailable", session_id=body.session_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "service_unavailable",
                "message": "Corpus not loaded. The assistant is initializing or failed to load its knowledge base.",
                "session_id": body.session_id,
            },
        )

    # --- Input guardrails ---
    if _GUARDRAILS_AVAILABLE:
        try:
            injection_result = block_injection(body.message)
            if injection_result.verdict == "blocked":
                logger.warning(
                    "guardrail.input_blocked_endpoint",
                    session_id=body.session_id,
                    reason=injection_result.reason,
                    details=injection_result.details,
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "input_blocked",
                        "message": injection_result.reason or "Input blocked by security guardrails.",
                        "session_id": body.session_id,
                    },
                )

            topic_result = reject_off_topic(body.message)
            if topic_result.verdict == "blocked":
                logger.warning(
                    "guardrail.topic_rejected_endpoint",
                    session_id=body.session_id,
                    reason=topic_result.reason,
                    details=topic_result.details,
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "off_topic",
                        "message": (
                            "This query is outside the scope of the tourism assistant. "
                        "Please ask about travel, dining, or attractions."
                    ),
                    "session_id": body.session_id,
                },
            )
        except HTTPException:
            raise  # re-raise intentional guardrail blocks
        except Exception as exc:
            logger.warning(
                "guardrail.degraded",
                session_id=body.session_id,
                error=str(exc),
                reason="input_guardrail_crash",
            )
            # Fail-open: continue to agent service

    if hasattr(agent_service, "_llm_service"):
        agent_service._llm_service = getattr(request.app.state, "llm_service", None)

    response = await agent_service.answer(
        session_id=body.session_id,
        message=body.message,
        language=body.language,
    )

    # --- Output grounding check ---
    if _GUARDRAILS_AVAILABLE:
        try:
            grounding_result = verify_grounding(response.message, response.citations)
            if grounding_result.verdict == "flagged":
                response.guardrail_status = "output_flagged"
                response.guardrail_reason = grounding_result.reason
                logger.warning(
                    "guardrail.output_flagged_endpoint",
                    session_id=body.session_id,
                    reason=grounding_result.reason,
                    details=grounding_result.details,
                )
            else:
                response.guardrail_status = "pass"
        except Exception as exc:
            logger.warning(
                "guardrail.degraded",
                session_id=body.session_id,
                error=str(exc),
                reason="grounding_check_crash",
            )
            # Fail-open: request still passes through
    else:
        logger.debug("guardrail.degraded", reason="guardrails_not_available")

    elapsed = (time.perf_counter() - t0) * 1000
    logger.info(
        "chat.response",
        session_id=body.session_id,
        intent=response.intent,
        latency_ms=response.latency_ms,
        total_ms=round(elapsed, 3),
        has_citations=len(response.citations) > 0,
        checkpoint_mode=getattr(agent_service, "checkpoint_mode", None),
        fallback=response.fallback,
    )

    return response

@router.get("/stream")
@limiter.limit("20/minute")
async def chat_stream(
    request: Request,
    message: str = Query(...),
    session_id: str = Query(...),
    language: str = Query("vi"),
) -> StreamingResponse:
    """Stream a grounded assistant answer as Server-Sent Events."""
    query = message.strip()
    sid = session_id.strip()
    if not query or not sid:
        return _error_stream("invalid_request")

    # --- Input guardrails (before stream starts) ---
    if _GUARDRAILS_AVAILABLE:
        try:
            injection_result = block_injection(query)
            if injection_result.verdict == "blocked":
                logger.warning(
                    "guardrail.input_blocked_stream",
                    session_id=sid,
                    reason=injection_result.reason,
                )
                return _error_stream(f"input_blocked: {injection_result.reason}")

            topic_result = reject_off_topic(query)
            if topic_result.verdict == "blocked":
                logger.warning(
                    "guardrail.topic_rejected_stream",
                    session_id=sid,
                    reason=topic_result.reason,
                )
                return _error_stream(
                    "off_topic: This query is outside the scope of the tourism assistant."
                )
        except Exception as exc:
            logger.warning(
                "guardrail.degraded",
                session_id=sid,
                error=str(exc),
                reason="input_guardrail_crash_stream",
            )
            # Fail-open: continue to stream

    agent_service = getattr(request.app.state, "agent_service", None)
    if not _agent_service_available(request):
        logger.error("sse.stream_error", reason="service_unavailable", session_id=sid)
        return _error_stream("service_unavailable")

    async def event_generator() -> AsyncGenerator[str, None]:
        logger.info(
            "sse.stream_start",
            language=language,
            session_id=sid,
            checkpoint_mode=getattr(agent_service, "checkpoint_mode", None),
        )
        try:
            async for event in agent_service.answer_stream(
                session_id=sid,
                message=query,
                language=language,
            ):
                yield _sse_payload(event)
        except Exception as exc:
            reason = type(exc).__name__
            logger.error("sse.stream_error", error=str(exc), reason=reason, session_id=sid)
            yield _sse_payload(f"[ERROR] {reason}")
            yield _sse_payload("[DONE]")
            return

        # --- Output guardrails (post-stream, cannot block — tokens already sent) ---
        if _GUARDRAILS_AVAILABLE:
            try:
                # Output guardrails need the full message and citations;
                # in stream mode we log a degraded notice since we can't
                # reconstruct the full response from SSE events here.
                logger.info(
                    "guardrail.degraded",
                    session_id=sid,
                    reason="output_guardrail_not_applicable_stream",
                    details="Streaming responses cannot be re-validated after tokens are sent.",
                )
            except Exception as exc:
                logger.warning(
                    "guardrail.degraded",
                    session_id=sid,
                    error=str(exc),
                )

        logger.info("sse.stream_complete", session_id=sid)
        yield _sse_payload("[DONE]")

    return _streaming_response(event_generator())
