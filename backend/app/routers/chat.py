"""Chat endpoints — primary user-facing API for the assistant.

Wires POST /chat to GroundedAnswerService, retrieving from the
in-memory corpus loaded at application startup.
"""

import time

import structlog
from fastapi import APIRouter, HTTPException, Request, status

from app.models.request import ChatRequest
from app.models.response import ChatResponse
from app.services.grounded_answer import GroundedAnswerService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/chat")


@router.post("", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    """Answer a user query using the grounded answer service.

    Retrieves relevant corpus chunks, composes a deterministic answer
    with citations, and returns a structured ChatResponse.

    Returns 503 with structured error if the corpus/retriever was not
    loaded during application startup.
    """
    t0 = time.perf_counter()

    # Check corpus loaded at startup
    retriever = getattr(request.app.state, "retriever", None)
    if retriever is None:
        logger.error("chat.corpus_not_loaded", session_id=body.session_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "service_unavailable",
                "message": "Corpus not loaded. The assistant is initializing or failed to load its knowledge base.",
                "session_id": body.session_id,
            },
        )

    # Create service and answer
    service = GroundedAnswerService(retriever)
    response = service.answer(body.message, body.language, body.session_id)

    elapsed = (time.perf_counter() - t0) * 1000
    logger.info(
        "chat.response",
        session_id=body.session_id,
        intent=response.intent,
        latency_ms=response.latency_ms,
        total_ms=round(elapsed, 3),
        has_citations=len(response.citations) > 0,
    )

    return response
