"""Chat endpoints — primary user-facing API for the assistant.

Wires POST /chat to GroundedAnswerService, retrieving from the
hybrid (dense+sparse) retriever when available, falling back to the
in-memory keyword retriever loaded at application startup.
"""

import time

import structlog
from fastapi import APIRouter, HTTPException, Request, status

from app.models.request import ChatRequest
from app.models.response import ChatResponse
from app.services.grounded_answer import GroundedAnswerService
from app.services.hybrid_retriever import HybridRetriever
from app.services.llm_answer_service import LLMAnswerService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/chat")


@router.post("", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    """Answer a user query using the grounded answer service.

    Prefers hybrid (Qdrant RRF) retrieval when available; falls back to
    in-memory keyword retrieval. Returns 503 if neither is loaded.

    Returns 503 with structured error if the corpus/retriever was not
    loaded during application startup.
    """
    t0 = time.perf_counter()

    retriever = getattr(request.app.state, "retriever", None)
    hybrid_retriever = getattr(request.app.state, "hybrid_retriever", None)

    # 503 guard — neither retrieval path is available
    if retriever is None and hybrid_retriever is None:
        logger.error("chat.corpus_not_loaded", session_id=body.session_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "service_unavailable",
                "message": "Corpus not loaded. The assistant is initializing or failed to load its knowledge base.",
                "session_id": body.session_id,
            },
        )

    service = GroundedAnswerService(retriever)
    llm_service: LLMAnswerService | None = getattr(request.app.state, "llm_service", None)

    if hybrid_retriever is not None:
        # Hybrid path: await async retrieval, then try LLM answer with fallback
        result, citations = await hybrid_retriever.search_with_citations(
            body.message, top_k=5
        )
        if llm_service is not None:
            try:
                response = await llm_service.answer(
                    chunks=result.chunks,
                    citations=citations,
                    query=body.message,
                    language=body.language,
                    session_id=body.session_id,
                )
            except Exception as exc:
                logger.warning(
                    "llm.fallback",
                    error=str(exc),
                    reason=type(exc).__name__,
                    session_id=body.session_id,
                )
                response = service.answer_from_chunks(
                    chunks=result.chunks,
                    citations=citations,
                    query=body.message,
                    language=body.language,
                    session_id=body.session_id,
                )
                response.fallback = True
        else:
            response = service.answer_from_chunks(
                chunks=result.chunks,
                citations=citations,
                query=body.message,
                language=body.language,
                session_id=body.session_id,
            )
    else:
        # Keyword-only fallback path
        response = service.answer(body.message, body.language, body.session_id)

    elapsed = (time.perf_counter() - t0) * 1000
    logger.info(
        "chat.response",
        session_id=body.session_id,
        intent=response.intent,
        latency_ms=response.latency_ms,
        total_ms=round(elapsed, 3),
        has_citations=len(response.citations) > 0,
        retrieval_mode="hybrid" if hybrid_retriever is not None else "keyword",
        fallback=response.fallback,
    )

    return response
