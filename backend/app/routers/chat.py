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

    if hasattr(agent_service, "_llm_service"):
        agent_service._llm_service = getattr(request.app.state, "llm_service", None)

    response = await agent_service.answer(
        session_id=body.session_id,
        message=body.message,
        language=body.language,
    )

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
        logger.info("sse.stream_complete", session_id=sid)

    return _streaming_response(event_generator())
