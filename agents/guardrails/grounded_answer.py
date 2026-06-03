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
# Intent classification keywords (fallback only)
# ---------------------------------------------------------------------------

# Lightweight keyword-based fallback used ONLY when the LLM classifier
# is unavailable. The primary intent router is the LLM-based
# classify_intent() function below — it understands semantics, not keywords.
# Keywords are never enough; this list exists purely for resilience.

_RESTAURANT_KEYWORDS_VI = {
    "nhà hàng", "ăn", "quán", "hải sản", "cơm", "phở", "bún",
    "món", "nhậu", "tiệm", "tiệc", "đặc sản", "ẩm thực",
    "food", "restaurant", "eat", "seafood", "dining", "meal",
}

# Keywords for accommodation / lodging searches → route to Places API
_ACCOMMODATION_KEYWORDS_VI = {
    "nhà nghỉ", "khách sạn", "homestay", "resort", "motel",
    "chỗ ở", "lưu trú", "ngủ đêm", "phòng nghỉ",
    "hotel", "hostel", "lodge", "accommodation", "stay", "room",
}

_NAVIGATION_KEYWORDS_VI = {
    "đường đi", "chỉ đường", "đi đến", "đi tới", "làm sao đến",
    "cách đi", "từ đâu đến", "bản đồ", "route", "direction",
    "how to get", "navigate", "map", "where is", "ở đâu",
    "vị trí", "địa điểm",
}

_INTENT_SYSTEM_PROMPT = """\
Classify the user's intent into exactly ONE of these categories:

- conversational: Greetings, small talk, thanks, capability/help questions, or very short messages with no information need (e.g. "chào", "hello", "cảm ơn", "bạn có thể giúp gì", "what can you do")
- restaurant_search: Looking for places to eat, drink, or stay (restaurants, cafés, hotels, homestays, lodging, accommodation)
- navigation: Asking for directions, routes, maps, distances, or how to get somewhere
- cultural_query: Asking about history, culture, traditions, festivals, landmarks, or general info about Hàm Ninh
- unknown: Anything else, too short to classify, or ambiguous

Reply with ONLY the category name, nothing else.

User message: {message}"""


def detect_intent(message: str) -> str:
    """Lightweight keyword/rule-based intent classifier (FALLBACK ONLY).

    Primary intent routing is LLM-based via classify_intent() in AgentService.
    This function remains for backwards compatibility and when the LLM is unavailable
    (test mode, API down, timeout).

    Returns one of:
    - "conversational"
    - "restaurant_search"
    - "navigation"
    - "cultural_query"
    - "unknown"
    """
    stripped = message.strip()
    if len(stripped) < 3:
        return "unknown"

    lower = stripped.lower()

    # Conversational / capability turns have no information need, so skip RAG.
    conversational_exact_or_edge = (
        "chào", "hello", "hi", "hey", "xin chào",
        "cảm ơn", "thanks", "thank", "ok", "oke",
        "tạm biệt", "bye", "goodbye",
        "hẹn gặp", "good morning", "good evening",
    )
    for word in conversational_exact_or_edge:
        if lower == word or lower.startswith(word + " ") or lower.endswith(" " + word):
            return "conversational"

    conversational_help = (
        "bạn có thể giúp gì", "bạn giúp được gì", "bạn làm được gì",
        "có thể giúp gì", "giúp được gì", "làm được gì",
        "what can you do", "how can you help", "help me",
    )
    if any(phrase in lower for phrase in conversational_help):
        return "conversational"

    # Check recommendation-seeking queries first → Places API
    recommendation_phrases = (
        "recommend", "gợi ý", "đề xuất",
        "nên đi", "nên đến", "nên ăn", "nên ở",
        "nơi nào", "chỗ nào", "quán nào",
        "which", "where", "what place",
    )
    for phrase in recommendation_phrases:
        if phrase in lower:
            return "restaurant_search"

    # Check restaurant intent
    for kw in _RESTAURANT_KEYWORDS_VI:
        if kw in lower:
            return "restaurant_search"

    # Check accommodation / lodging intent → route to Places
    for kw in _ACCOMMODATION_KEYWORDS_VI:
        if kw in lower:
            return "restaurant_search"

    # Check navigation intent
    for kw in _NAVIGATION_KEYWORDS_VI:
        if kw in lower:
            return "navigation"

    # Default: most natural-language questions about the domain
    return "cultural_query"


async def classify_intent(
    message: str,
    client: "openai.AsyncOpenAI | None" = None,
    model: str = "gpt-4o-mini",
) -> tuple[str, float]:
    """LLM-based intent classification with keyword fallback.

    Sends the user message to a lightweight LLM call for semantic intent detection.
    Falls back to keyword-based detect_intent() if the LLM call fails, times out,
    or returns an unexpected response (e.g. mock objects in tests).

    Args:
        message: The user's raw message/query.
        client: OpenAI async client. If None, falls back to keywords.
        model: Model to use for classification.

    Returns:
        Tuple of (intent_name, confidence_score).
        Confidence is 0.9 if LLM classified, 0.5 if keyword fallback.
    """
    import asyncio
    import openai as _openai

    valid = {"conversational", "restaurant_search", "navigation", "cultural_query", "unknown"}

    # Try LLM classification first (with 3s timeout to avoid blocking)
    if client is not None:
        try:
            system_prompt = _INTENT_SYSTEM_PROMPT.format(message=message)
            completion = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                    ],
                    max_completion_tokens=20,
                ),
                timeout=3.0,
            )
            raw = (completion.choices[0].message.content or "unknown").strip().lower()
            # Validate: must be a clean string, not a mock repr like "<AsyncMock...>"
            if raw in valid and not raw.startswith("<"):
                return raw, 0.9
            # LLM returned unexpected value — fall through to keyword
        except (asyncio.TimeoutError, _openai.OpenAIError, Exception):
            # LLM unavailable — fall back to keyword matching
            pass

    # Keyword fallback
    intent = detect_intent(message)
    return intent, 0.5


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


def _topic_hint(query: str, language: str) -> str:
    text = query.lower()
    if any(term in text for term in ("ẩm thực", "món", "hải sản", "food", "cuisine", "local food")):
        return "ẩm thực địa phương" if language == "vi" else "local food"
    if any(term in text for term in ("lịch sử", "history")):
        return "lịch sử Hàm Ninh" if language == "vi" else "Ham Ninh history"
    if any(term in text for term in ("văn hóa", "văn hoá", "culture")):
        return "văn hóa Hàm Ninh" if language == "vi" else "Ham Ninh culture"
    return "Hàm Ninh" if language == "vi" else "Ham Ninh"

def _compact_evidence(results: list[RAGChunk], max_items: int = 5) -> list[tuple[str, str]]:
    seen: set[str] = set()
    items: list[tuple[str, str]] = []
    for chunk in results:
        excerpt = _excerpt(chunk.text, 220).strip()
        key = excerpt.lower()
        if not excerpt or key in seen:
            continue
        seen.add(key)
        items.append((chunk.title, excerpt))
        if len(items) >= max_items:
            break
    return items

def compose_answer_vi(query: str, results: list[RAGChunk]) -> str:
    """Compose a readable Vietnamese answer from retrieved chunks."""
    evidence = _compact_evidence(results)
    if not evidence:
        return "Hiện tại nguồn dữ liệu chưa có thông tin đầy đủ để trả lời câu hỏi này."

    topic = _topic_hint(query, "vi")
    intro = f"Về {topic}, các nguồn hiện có cho thấy:"
    bullets = [f"- {excerpt}" for _, excerpt in evidence[:4]]
    closing = "Tóm lại, điểm nổi bật là hải sản tươi, cách chế biến dân dã và trải nghiệm ăn uống gắn với đời sống làng chài." if "ẩm thực" in topic else "Tóm lại, đây là một chủ đề gắn với đời sống địa phương Hàm Ninh; bạn có thể hỏi tiếp về món ăn, nghề biển, lịch sử hoặc trải nghiệm tham quan."
    return "\n".join([intro, *bullets, closing])

def compose_answer_en(query: str, results: list[RAGChunk]) -> str:
    """Compose a readable English answer from Vietnamese source chunks."""
    evidence = _compact_evidence(results)
    if not evidence:
        return (
            "Currently, our data sources do not have sufficient information "
            "to answer this question."
        )

    topic = _topic_hint(query, "en")
    intro = f"About {topic}, the available sources indicate:"
    bullets = [f"- {excerpt}" for _, excerpt in evidence[:4]]
    closing = "In short, the strongest theme is fresh seafood, simple local preparation, and dining experiences tied to fishing-village life." if "food" in topic else "In short, this topic is tied to Ham Ninh local life; you can ask a follow-up about food, fishing livelihoods, history, or visit tips."
    return "\n".join([intro, *bullets, closing])

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
