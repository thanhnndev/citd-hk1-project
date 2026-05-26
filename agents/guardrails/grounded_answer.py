"""Grounded answer service — deterministic answer composition over retrieved chunks.

Pure-Python service with no FastAPI dependency.  Provides:
- Rule-based intent classification (restaurant_search, navigation, cultural_query, unknown)
- Deterministic Vietnamese and English answer composition from top retrieved chunks
- Honest no-evidence responses that make zero cultural/geographic/historical claims
- Structured logging for intent classification and corpus-gap analysis
"""

from __future__ import annotations

import logging
import time
from typing import List

from app.models.rag import RAGChunk
from app.models.response import ChatResponse, Citation
from agents.tools.retriever import Retriever, RetrievalResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intent classification keywords
# ---------------------------------------------------------------------------

_RESTAURANT_KEYWORDS_VI = {
    "nhà hàng", "ăn", "quán", "hải sản", "cơm", "phở", "bún",
    "món", "nhậu", "tiệm", "tiệc", "đặc sản", "ẩm thực",
    "food", "restaurant", "eat", "seafood", "dining", "meal",
}

_NAVIGATION_KEYWORDS_VI = {
    "đường đi", "chỉ đường", "đi đến", "đi tới", "làm sao đến",
    "cách đi", "từ đâu đến", "bản đồ", "route", "direction",
    "how to get", "navigate", "map", "where is", "ở đâu",
    "vị trí", "địa điểm",
}


def detect_intent(message: str) -> str:
    """Lightweight keyword/rule-based intent classifier.

    Returns one of:
    - "restaurant_search"
    - "navigation"
    - "cultural_query"
    - "unknown"
    """
    stripped = message.strip()
    if len(stripped) < 3:
        return "unknown"

    lower = stripped.lower()

    # Check restaurant intent
    for kw in _RESTAURANT_KEYWORDS_VI:
        if kw in lower:
            return "restaurant_search"

    # Check navigation intent
    for kw in _NAVIGATION_KEYWORDS_VI:
        if kw in lower:
            return "navigation"

    # Default: most natural-language questions about the domain
    return "cultural_query"


# ---------------------------------------------------------------------------
# Answer composition
# ---------------------------------------------------------------------------

_EXCERPT_MAX_CHARS = 150


def _excerpt(text: str, max_chars: int = _EXCERPT_MAX_CHARS) -> str:
    """Return a safe excerpt of text, truncated at word boundary."""
    if len(text) <= max_chars:
        return text
    # Truncate at last space to avoid cutting mid-word
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars // 2:
        return truncated[:last_space] + "..."
    return truncated + "..."


def compose_answer_vi(query: str, results: list[RAGChunk]) -> str:
    """Compose a Vietnamese answer from retrieved chunks.

    Format:
    - Single chunk: "Theo {source}: {excerpt}"
    - Multiple chunks (up to 3): paragraph combining excerpts with context.
    """
    top = results[:3]

    if len(top) == 0:
        return "Hiện tại nguồn dữ liệu chưa có thông tin đầy đủ để trả lời câu hỏi này."

    if len(top) == 1:
        chunk = top[0]
        excerpt = _excerpt(chunk.text)
        return f"Theo {chunk.title}: {excerpt}"

    # Multiple chunks — build a coherent paragraph
    parts: list[str] = []
    for chunk in top:
        excerpt = _excerpt(chunk.text)
        parts.append(f"{chunk.title}: {excerpt}")

    combined = ". ".join(parts)
    return f"Dựa trên thông tin thu thập được: {combined}."


def compose_answer_en(query: str, results: list[RAGChunk]) -> str:
    """Compose an English answer from Vietnamese source chunks.

    Acknowledges the Vietnamese source material with English framing.
    """
    top = results[:3]

    if len(top) == 0:
        return (
            "Currently, our data sources do not have sufficient information "
            "to answer this question."
        )

    if len(top) == 1:
        chunk = top[0]
        excerpt = _excerpt(chunk.text)
        return f"Based on Vietnamese source material from {chunk.title}: {excerpt}"

    parts: list[str] = []
    for chunk in top:
        excerpt = _excerpt(chunk.text)
        parts.append(f"From {chunk.title}: {excerpt}")

    combined = ". ".join(parts)
    return f"Based on Vietnamese source material: {combined}."


# ---------------------------------------------------------------------------
# No-evidence messages (honest — zero fabricated claims)
# ---------------------------------------------------------------------------

_NO_EVIDENCE_VI = (
    "Hiện tại nguồn dữ liệu chưa có thông tin đầy đủ "
    "để trả lời câu hỏi này."
)

_NO_EVIDENCE_EN = (
    "Currently, our data sources do not have sufficient information "
    "to answer this question."
)

_NO_EVIDENCE_BY_LANG = {
    "vi": _NO_EVIDENCE_VI,
    "en": _NO_EVIDENCE_EN,
}


def _no_evidence_message(language: str) -> str:
    """Return honest no-evidence message for the given language.

    Never makes cultural, geographic, or historical claims.
    """
    return _NO_EVIDENCE_BY_LANG.get(
        language.lower(), _NO_EVIDENCE_EN
    )


# ---------------------------------------------------------------------------
# GroundedAnswerService
# ---------------------------------------------------------------------------

class GroundedAnswerService:
    """Pure-Python service that composes grounded answers from retrieved chunks.

    Constructor takes a ``Retriever`` instance; ``answer()`` returns a
    fully-formed ``ChatResponse`` for both hit and miss cases.
    """

    def __init__(self, retriever: Retriever) -> None:
        self._retriever = retriever

    def answer_from_chunks(
        self,
        chunks: list[RAGChunk],
        citations: list[Citation],
        query: str,
        language: str = "vi",
        session_id: str | None = None,
    ) -> ChatResponse:
        """Compose a grounded answer from pre-fetched chunks and citations.

        Skips the retrieval step — use this when the caller has already
        awaited HybridRetriever.search_with_citations() and wants to hand
        off the result synchronously.

        Args:
            chunks: Pre-retrieved RAGChunk objects (already ranked).
            citations: Corresponding Citation objects for the chunks.
            query: Original user query (used for intent detection and logging).
            language: Preferred response language ("vi" or "en").
            session_id: Opaque session identifier for correlation.

        Returns:
            ChatResponse with message, citations, intent, latency_ms, etc.
        """
        t0 = time.perf_counter()
        sid = session_id or ""
        intent = detect_intent(query)

        if not chunks:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.info(
                "no_evidence query=%s intent=%s", query, intent,
                extra={"session_id": sid, "language": language},
            )
            return ChatResponse(
                session_id=sid,
                message=_no_evidence_message(language),
                citations=[],
                places=[],
                intent=intent,
                langfuse_trace_id=None,
                latency_ms=round(elapsed, 3),
            )

        if language.lower() == "en":
            message = compose_answer_en(query, chunks)
        else:
            message = compose_answer_vi(query, chunks)

        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(
            "answer_composed query=%s intent=%s chunks=%d latency_ms=%.1f",
            query, intent, len(chunks), elapsed,
            extra={"session_id": sid, "language": language},
        )

        return ChatResponse(
            session_id=sid,
            message=message,
            citations=citations,
            places=[],
            intent=intent,
            langfuse_trace_id=None,
            latency_ms=round(elapsed, 3),
        )

    # ------------------------------------------------------------------
    # Internal helpers (kept here for single-file discoverability)
    # ------------------------------------------------------------------

    def answer(
        self, query: str, language: str, session_id: str
    ) -> ChatResponse:
        """Answer a query by retrieving relevant chunks and composing a response.

        Args:
            query: User's natural-language query.
            language: Preferred response language ("vi" or "en").
            session_id: Opaque session identifier for correlation.

        Returns:
            ChatResponse with message, citations, intent, latency_ms, etc.
        """
        t0 = time.perf_counter()
        intent = detect_intent(query)

        try:
            retrieval_result, citations = self._retriever.search_with_citations(
                query, top_k=5
            )
        except Exception as exc:
            logger.error(
                "retrieval_error query=%s error=%s", query, exc,
                extra={"intent": intent, "session_id": session_id},
            )
            elapsed = (time.perf_counter() - t0) * 1000
            return ChatResponse(
                session_id=session_id,
                message=_no_evidence_message(language),
                citations=[],
                places=[],
                intent=intent,
                langfuse_trace_id=None,
                latency_ms=round(elapsed, 3),
            )

        elapsed = (time.perf_counter() - t0) * 1000

        if not retrieval_result.chunks:
            # Honest no-evidence — log at info for corpus-gap analysis
            logger.info(
                "no_evidence query=%s intent=%s", query, intent,
                extra={"session_id": session_id, "language": language},
            )
            return ChatResponse(
                session_id=session_id,
                message=_no_evidence_message(language),
                citations=[],
                places=[],
                intent=intent,
                langfuse_trace_id=None,
                latency_ms=round(elapsed, 3),
            )

        # Compose grounded answer from retrieved chunks
        if language.lower() == "en":
            message = compose_answer_en(query, retrieval_result.chunks)
        else:
            message = compose_answer_vi(query, retrieval_result.chunks)

        logger.info(
            "answer_composed query=%s intent=%s chunks=%d latency_ms=%.1f",
            query, intent, len(retrieval_result.chunks), elapsed,
            extra={"session_id": session_id, "language": language},
        )

        return ChatResponse(
            session_id=session_id,
            message=message,
            citations=citations,
            places=[],
            intent=intent,
            langfuse_trace_id=None,
            latency_ms=round(elapsed, 3),
        )
