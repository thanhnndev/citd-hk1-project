"""Follow-up context detection and response composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.models.response import ChatResponse
from agents.graph.state import AgentState, FollowUpDecision
from agents.graph.routing import _direct_answer as _default_direct_answer, _clarify_message as _default_clarify_message, _is_followup
from agents.services.place_recommendation_service import PLACE_RECOMMENDATION_INTENT

logger = structlog.get_logger(__name__)


def _norm(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


@dataclass
class PlaceMemory:
    """Structured short-term memory for one place from the latest response."""

    index: int
    place_id: str
    name: str
    reviews: list[dict[str, Any]] = field(default_factory=list)
    hours: dict[str, Any] = field(default_factory=dict)
    rating: float | None = None
    price_level: int | None = None

    @property
    def aliases(self) -> list[str]:
        normalized = _norm(self.name)
        aliases = [normalized] if normalized else []
        distinctive = [t for t in normalized.split() if len(t) > 1 and t not in _PLACE_DESCRIPTOR_TOKENS]
        aliases.extend(distinctive)
        return aliases

@dataclass
class FollowUpResolution:
    """Typed resolver output used before tool routing."""

    decision: FollowUpDecision
    field: str | None = None
    place: PlaceMemory | None = None
    confidence: float = 0.0
    reason: str = ""

_PLACE_DESCRIPTOR_TOKENS = frozenset({
    "quán", "nhà", "hàng", "khách", "sạn", "bè", "hải", "sản",
    "homestay", "hotel", "restaurant", "seafood", "ăn", "uống", "nghỉ", "dưỡng", "resort",
})
_QUERY_DETAIL_TOKENS = frozenset({
    "giá", "bao", "nhiêu", "mở", "cửa", "đường", "đi", "review", "rating",
    "đánh", "rẻ", "gần", "xa", "price", "cost", "hours", "open", "giờ",
})

@dataclass
class FollowUpContext:
    """Structured metadata from the most recent assistant response.

    Persisted alongside plain-text history so that unseen follow-ups can
    resolve references to prior places, score breakdowns, explanations,
    provider trace/status, and prior assistant content without RAG fallback.

    Redaction guarantee: no API keys, DSNs, raw provider payloads, exact
    user GPS, or full conversation content beyond bounded assistant
    summaries already visible to the user.
    """

    session_id: str = ""
    intent: str | None = None
    place_ids: list[str] = field(default_factory=list)
    place_display_names: list[str] = field(default_factory=list)
    place_ratings: list[float] = field(default_factory=list)
    place_price_levels: list[int] = field(default_factory=list)
    place_reviews: list[list[dict[str, Any]]] = field(default_factory=list)
    place_hours: list[dict[str, Any]] = field(default_factory=list)
    has_citations: bool = False
    citation_sources: list[str] = field(default_factory=list)
    reasoning_log_summary: str | None = None
    last_user_topic: str | None = None
    score_breakdown_keys: list[str] = field(default_factory=list)
    provider_source: str | None = None
    provider_status: str | None = None
    fallback: bool = False
    explanation_keys: list[str] = field(default_factory=list)
    _version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "intent": self.intent,
            "place_ids": self.place_ids,
            "place_display_names": self.place_display_names,
            "place_ratings": self.place_ratings,
            "place_price_levels": self.place_price_levels,
            "place_reviews": self.place_reviews,
            "place_hours": self.place_hours,
            "has_citations": self.has_citations,
            "citation_sources": self.citation_sources,
            "reasoning_log_summary": self.reasoning_log_summary,
            "last_user_topic": self.last_user_topic,
            "score_breakdown_keys": self.score_breakdown_keys,
            "provider_source": self.provider_source,
            "provider_status": self.provider_status,
            "fallback": self.fallback,
            "explanation_keys": self.explanation_keys,
            "_version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "FollowUpContext | None":
        if not isinstance(data, dict):
            return None
        def _safe_list(val: Any) -> list[str]:
            if isinstance(val, list):
                return [str(v) for v in val if v]
            return []
        def _safe_float_list(val: Any) -> list[float]:
            if isinstance(val, list):
                return [float(v) for v in val if v is not None]
            return []
        def _safe_int_list(val: Any) -> list[int]:
            if isinstance(val, list):
                return [int(v) for v in val if v is not None]
            return []
        try:
            return cls(
                session_id=data.get("session_id", ""),
                intent=data.get("intent"),
                place_ids=_safe_list(data.get("place_ids")),
                place_display_names=_safe_list(data.get("place_display_names")),
                place_ratings=_safe_float_list(data.get("place_ratings")),
                place_price_levels=_safe_int_list(data.get("place_price_levels")),
                place_reviews=data.get("place_reviews") if isinstance(data.get("place_reviews"), list) else [],
                place_hours=data.get("place_hours") if isinstance(data.get("place_hours"), list) else [],
                has_citations=bool(data.get("has_citations")),
                citation_sources=_safe_list(data.get("citation_sources")),
                reasoning_log_summary=data.get("reasoning_log_summary"),
                last_user_topic=data.get("last_user_topic"),
                score_breakdown_keys=_safe_list(data.get("score_breakdown_keys")),
                provider_source=data.get("provider_source"),
                provider_status=data.get("provider_status"),
                fallback=bool(data.get("fallback")),
                explanation_keys=_safe_list(data.get("explanation_keys")),
                _version=data.get("_version", 1),
            )
        except (TypeError, AttributeError):
            return None

    @property
    def is_populated(self) -> bool:
        return bool(
            self.place_ids
            or self.place_display_names
            or self.place_reviews
            or self.place_hours
            or self.citation_sources
            or self.reasoning_log_summary
            or self.last_user_topic
            or self.score_breakdown_keys
            or self.provider_source
        )


def _place_memories(context: FollowUpContext) -> list[PlaceMemory]:
    memories: list[PlaceMemory] = []
    for index, name in enumerate(context.place_display_names):
        memories.append(PlaceMemory(
            index=index,
            place_id=context.place_ids[index] if index < len(context.place_ids) else "",
            name=name,
            rating=context.place_ratings[index] if index < len(context.place_ratings) else None,
            price_level=context.place_price_levels[index] if index < len(context.place_price_levels) else None,
            reviews=context.place_reviews[index] if index < len(context.place_reviews) else [],
            hours=context.place_hours[index] if index < len(context.place_hours) and isinstance(context.place_hours[index], dict) else {},
        ))
    return memories

def _requested_followup_field(text: str) -> str | None:
    if any(term in text for term in ("review", "đánh giá", "nhận xét", "bình luận")):
        return "reviews"
    if any(term in text for term in ("giờ", "mở cửa", "open", "hours")):
        return "hours"
    if any(term in text for term in ("đường", "bản đồ", "map", "route", "direction", "chỉ đường")):
        return "directions"
    if any(term in text for term in ("vì sao", "tại sao", "xếp hạng", "score", "điểm")):
        return "score"
    if any(term in text for term in ("nguồn", "provider", "data source")):
        return "source"
    return None

def _resolve_place_followup(message: str, context: FollowUpContext) -> FollowUpResolution:
    text = _norm(message)
    field = _requested_followup_field(text)
    best: PlaceMemory | None = None
    best_score = 0.0
    for place in _place_memories(context):
        normalized = _norm(place.name)
        distinctive = [t for t in normalized.split() if len(t) > 1 and t not in _PLACE_DESCRIPTOR_TOKENS]
        descriptor = [t for t in normalized.split() if len(t) > 1 and t in _PLACE_DESCRIPTOR_TOKENS]
        score = 0.0
        if normalized and normalized in text:
            score += 10.0
        score += sum(2.0 for token in distinctive if token in text)
        score += min(1.0, sum(0.25 for token in descriptor if token in text))
        if score > best_score:
            best_score = score
            best = place
    if best and best_score >= 1.5:
        return FollowUpResolution("structured_context", field=field, place=best, confidence=best_score, reason="place_match")
    demonstratives = ("này", "kia", "đó", "that", "this")
    if any(term in text for term in demonstratives) and context.intent == PLACE_RECOMMENDATION_INTENT and len(context.place_display_names) == 1:
        memories = _place_memories(context)
        return FollowUpResolution("structured_context", field=field, place=memories[0] if memories else None, confidence=1.0, reason="single_place_demonstrative")
    if field in {"score", "source"}:
        return FollowUpResolution("structured_context", field=field, confidence=0.8, reason="context_field")
    if field and context.intent == PLACE_RECOMMENDATION_INTENT and context.place_display_names:
        return FollowUpResolution("clarification_needed", field=field, confidence=0.5, reason="field_without_place")
    return FollowUpResolution("insufficient_context", field=field, confidence=0.0, reason="no_place_match")

def resolve_followup_decision(
    message: str,
    context: FollowUpContext | None,
    history: list[dict[str, str]] | None = None,
) -> FollowUpDecision:
    """Classify a follow-up message into a decision label.

    Priority order:
    1. structured_context — message references entities in the prior structured context
    2. history_context — message is answerable from conversation history alone
    3. clarification_needed — ambiguous pronoun or underspecified follow-up
    4. insufficient_context — no prior context or history to resolve from

    Returns a label that callers can use to route the follow-up appropriately
    (answer from context, ask clarification, or trigger RAG).
    """
    text = _norm(message)
    if not text:
        return "insufficient_context"

    # 1. Explicit new requests should route normally before any prior-place
    # token matching. This prevents broad category overlap (e.g. "hải sản")
    # from hijacking a fresh search after place recommendations.
    if _is_explicit_new_request(message):
        return "insufficient_context"

    # 2. Try structured context for genuine follow-ups.
    if context and context.is_populated:
        if _is_knowledge_topic_followup(text, context) or _is_knowledge_topic_refinement(text, context):
            return "insufficient_context"
        resolution = _resolve_place_followup(message, context)
        if resolution.decision == "structured_context":
            return "structured_context"
        if resolution.decision == "clarification_needed":
            return "clarification_needed"
        if _matches_structured_context(text, context):
            return "structured_context"

    # 3. Fall back to history-only heuristics
    if history and _is_followup(text, history):
        return "history_context"

    # 3. Ambiguous pronouns that could reference missing context
    if _is_ambiguous_pronoun_followup(text):
        return "clarification_needed"

    # 4. No context to resolve from
    if not context or not context.is_populated:
        return "insufficient_context"

    # If it is a brand-new descriptive request (doesn't match structured context),
    # treat it as insufficient_context so normal routing handles it, rather than
    # getting stuck in a clarification loop.
    if _is_new_request(message):
        return "insufficient_context"

    return "clarification_needed"


def _is_knowledge_topic_followup(text: str, context: FollowUpContext) -> bool:
    if context.intent not in {"cultural_query", "knowledge", "followup_history"}:
        return False
    return any(term in text for term in (
        "hỏi thêm", "chủ đề này", "nói thêm", "kể thêm", "tiếp tục",
        "more about this", "follow up", "tell me more"
    ))

def _is_knowledge_topic_refinement(text: str, context: FollowUpContext) -> bool:
    if context.intent not in {"cultural_query", "knowledge"} or len(text.split()) > 3:
        return False
    topic_terms = (
        "hải sản", "hai san", "ghẹ", "ghe", "tôm", "tom", "mực", "muc", "ẩm thực", "am thuc",
        "văn hóa", "văn hoá", "van hoa", "lịch sử", "lich su", "nghề biển", "nghe bien",
    )
    return any(term in text for term in topic_terms)

def _matches_structured_context(text: str, context: FollowUpContext) -> bool:
    """Check if the follow-up message references entities in the structured context.

    Ignores common Vietnamese descriptor words (quán, nhà hàng, hải sản, etc.)
    so that new place requests like "tìm quán cà phê" don't falsely match
    prior context. A place name must have at least one distinctive token
    remaining after filtering.
    """
    # Common descriptor words that appear in many place names but don't
    # uniquely identify a specific venue. Kept conservative — only words that
    # are nearly always generic (not distinctive like "hải sản" or "ngọc lan").
    _skip_tokens = frozenset({
        "quán", "nhà", "hàng", "khách", "sạn", "bè", "hải", "sản",
        "homestay", "hotel", "restaurant", "seafood",
        "ăn", "uống", "nghỉ", "dưỡng", "resort",
    })
    generic_query_tokens = {
        "giá", "bao", "nhiêu", "mở", "cửa", "đường", "đi", "review", "rating",
        "đánh", "giá", "rẻ", "gần", "xa", "price", "cost", "hours", "open",
    }

    # Direct place name references (token-level, ignoring single-char tokens
    # and common descriptor words). At least one distinctive token must match.
    for name in context.place_display_names:
        normalized = _norm(name)
        if not normalized:
            continue
        tokens = [t for t in normalized.split() if len(t) > 1 and t not in _skip_tokens]
        if not tokens:
            # If the place name is entirely generic descriptors, only match
            # descriptor overlap when the message is framed as a follow-up.
            name_tokens = [t for t in normalized.split() if len(t) > 1]
            if normalized in text or (name_tokens and any(t in text for t in name_tokens)):
                return True
            continue
        matched = [token for token in tokens if token in text]
        if any(token not in generic_query_tokens for token in matched):
            return True

    # References to scoring/ranking
    if context.score_breakdown_keys and any(
        term in text for term in ("vì sao", "tại sao", "sao lại", "xếp hạng", "rank", "score", "điểm số", "điểm cao", "điểm thấp", "why", "ranked")
    ):
        return True

    # References to citations/sources
    if context.has_citations and any(
        term in text for term in ("nguồn", "source", "trích", "cite", "tài liệu", "document")
    ):
        return True

    # References to provider/source
    if context.provider_source and any(
        term in text for term in ("provider", "nguồn dữ liệu", "data source")
    ):
        return True

    # References to recommendations (places intent with populated context)
    # Use demonstratives and specific terms — NOT generic "quán" which appears
    # in new place requests unless accompanied by comparatives or rating terms
    if context.intent == PLACE_RECOMMENDATION_INTENT and any(
        term in text for term in (
            "địa điểm", "này", "kia", "đó", "place", "venue", "recommend", "gợi ý",
            "nào", "nhất", "quán nào", "chỗ nào", "địa điểm nào", "best", "top", "rank",
            "xếp hạng", "cao nhất", "thấp nhất", "rẻ nhất", "gần nhất", "đánh giá", "rating",
            "review"
        )
    ):
        return True

    return False


def _is_ambiguous_pronoun_followup(text: str) -> bool:
    """Detect follow-ups that use pronouns without clear referents."""
    text = _norm(text)
    # Strip trailing/leading punctuation for pronoun matching
    text = text.strip("?.,!;:").strip()
    ambiguous = {"nó", "chúng", "chúng nó", "đó", "kia", "ấy", "that", "those", "they", "them"}
    words = set(text.split())
    return bool(words & ambiguous) and len(text.split()) <= 4


def _build_followup_context(response: ChatResponse) -> FollowUpContext:
    """Extract structured context from a ChatResponse for follow-up resolution."""
    place_ids = [p.place_id for p in response.places[:10]]
    place_names = [p.display_name for p in response.places[:10]]
    place_ratings = [float(p.rating or 0.0) for p in response.places[:10]]
    place_price_levels = [int(p.price_level or 0) for p in response.places[:10]]
    place_reviews = [p.reviews[:3] for p in response.places[:10]]
    place_hours = [p.current_opening_hours or p.regular_opening_hours or {} for p in response.places[:10]]
    citation_sources = [c.source for c in response.citations[:5]]

    score_keys: list[str] = []
    explanation_keys: list[str] = []
    for p in response.places[:5]:
        if p.score_breakdown:
            score_keys.extend(str(k) for k in p.score_breakdown.model_dump().keys() if k not in score_keys)
        if p.explanation:
            explanation_keys.extend(str(k) for k in p.explanation.model_dump().keys() if k not in explanation_keys)

    return FollowUpContext(
        session_id=response.session_id,
        intent=response.intent,
        place_ids=place_ids,
        place_display_names=place_names,
        place_ratings=place_ratings,
        place_price_levels=place_price_levels,
        place_reviews=place_reviews,
        place_hours=place_hours,
        has_citations=bool(response.citations),
        citation_sources=citation_sources,
        reasoning_log_summary=(response.reasoning_log or "")[:500] if response.reasoning_log else None,
        score_breakdown_keys=score_keys[:10],
        provider_source=getattr(response.decision_trace, "provider_source", None) if response.decision_trace else None,
        provider_status=getattr(response.decision_trace, "credential_status", None) if response.decision_trace else None,
        fallback=response.fallback,
        explanation_keys=explanation_keys[:10],
    )

def compose_followup_answer(
    message: str,
    context: FollowUpContext,
    language: str,
) -> str:
    """Compose a contextual follow-up answer from structured last-response context.

    Uses pattern-matching guardrails (not hardcoded example strings) to detect
    the type of follow-up and compose an appropriate answer. Never invents
    facts — when context lacks details, provides a bounded acknowledgment.
    """
    text = _norm(message)

    resolution = _resolve_place_followup(message, context)
    if resolution.decision == "structured_context" and resolution.place is not None:
        place = resolution.place
        name = place.name
        if resolution.field == "reviews":
            lines = []
            for review in place.reviews[:3]:
                rating = review.get("rating")
                body = review.get("text")
                if body:
                    prefix = f"{rating}⭐: " if rating else "- "
                    lines.append(prefix + str(body))
            if lines:
                return (f"Một vài review về {name}:\n" + "\n".join(lines)) if language == "vi" else (f"A few reviews for {name}:\n" + "\n".join(lines))
            return f"Mình chưa có nội dung review cụ thể cho {name} trong dữ liệu hiện có." if language == "vi" else f"I do not have review text for {name} in the current data."
        if resolution.field == "hours":
            descriptions = place.hours.get("weekdayDescriptions") or place.hours.get("weekday_descriptions") or []
            open_now = place.hours.get("openNow")
            if descriptions:
                return (f"Giờ mở cửa của {name}:\n" + "\n".join(str(item) for item in descriptions[:7])) if language == "vi" else (f"Opening hours for {name}:\n" + "\n".join(str(item) for item in descriptions[:7]))
            if isinstance(open_now, bool):
                status = "đang mở cửa" if open_now else "hiện không mở cửa"
                return f"{name} {status}, nhưng mình chưa có lịch giờ chi tiết." if language == "vi" else f"{name} is {'open now' if open_now else 'not open now'}, but I do not have detailed hours."
            return f"Về {name}: mình đã gợi ý địa điểm này trước đó, nhưng chưa có giờ mở cửa chi tiết." if language == "vi" else f"About {name}: I recommended it earlier, but I do not have detailed opening hours."
        if language == "vi":
            return f"Về {name}: bạn muốn xem review, giờ mở cửa, đường đi hay lý do xếp hạng?"
        return f"About {name}: do you want reviews, opening hours, directions, or ranking reasons?"

    if resolution.decision == "clarification_needed" and resolution.field in {"reviews", "hours", "directions", "score"}:
        names = ", ".join(context.place_display_names[:3])
        if language == "vi":
            return f"Bạn muốn hỏi {resolution.field} của địa điểm nào? Một vài lựa chọn: {names}."
        return f"Which place do you want {resolution.field} for? Options include: {names}."

    # Score / ranking reference
    if context.score_breakdown_keys and any(
        term in text for term in ("vì sao", "tại sao", "sao lại", "xếp hạng", "rank", "score", "điểm số", "điểm cao", "điểm thấp", "why")
    ):
        keys = ", ".join(context.score_breakdown_keys[:3])
        if language == "vi":
            return (
                f"Địa điểm được xếp hạng dựa trên các tiêu chí: {keys}. "
                f"Yếu tố địa phương (local_factor) và chất lượng đóng vai trò chính."
            )
        return (
            f"Places were ranked using: {keys}. "
            f"Local factor and quality scores are the main drivers."
        )

    # Citation / source reference
    if context.has_citations and any(
        term in text for term in ("nguồn", "source", "trích", "cite", "tài liệu", "document")
    ):
        sources = ", ".join(context.citation_sources[:2]) if context.citation_sources else "các nguồn đã tham khảo"
        if language == "vi":
            return f"Thông tin trước đó được tham khảo từ: {sources}. Bạn cần kiểm tra nguồn cụ thể nào?"
        return f"Previous info was sourced from: {sources}. Which source would you like to check?"

    # Provider / data source reference
    if context.provider_source and any(
        term in text for term in ("provider", "nguồn dữ liệu", "data source")
    ):
        src = context.provider_source
        status = context.provider_status or "unknown"
        if language == "vi":
            return f"Dữ liệu địa điểm lấy từ {src} (trạng thái: {status})."
        return f"Place data comes from {src} (status: {status})."

    # Comparative rating query (e.g., highest rated, best review)
    if context.place_ratings and any(term in text for term in ("đánh giá cao nhất", "rating cao nhất", "highest rated", "best rated", "review cao nhất", "đánh giá tốt nhất", "ngon nhất", "ok nhất")):
        max_rating = -1.0
        best_indices = []
        for i, r in enumerate(context.place_ratings):
            if r > max_rating:
                max_rating = r
                best_indices = [i]
            elif r == max_rating:
                best_indices.append(i)
        
        if best_indices:
            best_places = [context.place_display_names[idx] for idx in best_indices]
            joined_names = " và ".join(best_places) if language == "vi" else " and ".join(best_places)
            if language == "vi":
                return f"Trong các địa điểm đã gợi ý, nơi có đánh giá cao nhất là {joined_names} với {max_rating}⭐."
            return f"Among the recommended places, the highest rated is {joined_names} with {max_rating}⭐."

    # Comparative price query (e.g., cheapest, best price, lowest cost)
    if context.place_price_levels and any(term in text for term in ("rẻ nhất", "giá thấp nhất", "cheapest", "lowest price", "giá tốt nhất", "chi phí tiết kiệm nhất", "tiết kiệm nhất")):
        min_price = 999
        best_indices = []
        for i, p in enumerate(context.place_price_levels):
            val = p if p > 0 else 2
            if val < min_price:
                min_price = val
                best_indices = [i]
            elif val == min_price:
                best_indices.append(i)
        
        if best_indices and min_price < 999:
            best_places = [context.place_display_names[idx] for idx in best_indices]
            joined_names = " và ".join(best_places) if language == "vi" else " and ".join(best_places)
            price_desc = "giá tiết kiệm" if min_price == 1 else "giá hợp lý"
            if language == "vi":
                return f"Trong các địa điểm đã gợi ý, nơi có chi phí tiết kiệm nhất là {joined_names} ({price_desc})."
            return f"Among the recommended places, the most budget-friendly is {joined_names}."

    # General recommendation follow-up
    if context.intent == PLACE_RECOMMENDATION_INTENT and any(
        term in text for term in ("quán", "địa điểm", "này", "kia", "đó", "place", "venue", "gợi ý")
    ):
        names = ", ".join(context.place_display_names[:3]) if context.place_display_names else "các địa điểm đã gợi ý"
        if language == "vi":
            return f"Bạn muốn biết thêm gì về {names}? Mình có thể giải thích lý do xếp hạng hoặc gợi ý thêm."
        return f"What would you like to know more about {names}? I can explain rankings or suggest more."

    # Default: bounded acknowledgment
    if language == "vi":
        return "Mình nhớ câu trả lời trước đó. Bạn cần giải thích thêm phần nào?"
    return "I remember the previous answer. Which part would you like me to explain further?"


def _is_explicit_new_request(message: str) -> bool:
    """Return True for messages that clearly start a new tool/search task.

    This is intentionally stricter than _is_new_request: it requires an
    explicit action/search signal so follow-ups like "Hải Sản có tươi không?"
    can still resolve against a previously recommended place named "Quán Hải Sản".
    """
    text = _norm(message)
    if not text:
        return False

    place_terms = (
        "nhà hàng", "quán", "đồ ngon", "món ngon", "ăn", "hải sản", "cafe", "cà phê",
        "khách sạn", "homestay", "lưu trú", "chỗ ở", "hotel", "restaurant", "seafood",
        "stay", "place", "nearby", "gần đây", "quanh đây", "cf", "coffee", "view"
    )
    action_terms = (
        "kiếm", "tìm", "gợi ý", "đề xuất", "recommend", "find", "search",
        "quanh", "gần", "ở đâu", "có quán", "có nhà hàng",
        "lịch trình", "bản đồ", "map"
    )
    knowledge_terms = ("văn hóa", "lịch sử", "culture", "history", "truyền thống", "dân chài")

    has_place_topic = any(term in text for term in place_terms)
    has_action = any(term in text for term in action_terms)
    has_knowledge = any(term in text for term in knowledge_terms)
    return (has_place_topic and has_action) or has_knowledge

def _is_new_request(message: str) -> bool:
    """Detect whether a message looks like a brand-new place or knowledge
    request rather than a follow-up to prior context.

    Used to avoid short-circuiting new requests into clarification when
    prior context exists but doesn't match the message.
    """
    text = _norm(message)
    # New place request indicators
    place_terms = (
        "nhà hàng", "quán", "đồ ngon", "món ngon", "ăn", "hải sản", "cafe", "cà phê",
        "khách sạn", "homestay", "lưu trú", "chỗ ở", "hotel", "restaurant", "seafood",
        "stay", "place", "nearby", "gần đây", "quanh đây", "cf", "coffee", "view"
    )
    action_terms = (
        "kiếm", "tìm", "gợi ý", "đề xuất", "recommend", "find", "search",
        "có", "nào", "đâu", "gì", "quanh", "gần", "ở", "không", "review",
        "đánh giá", "giá", "sao", "lịch trình", "bản đồ", "map"
    )
    # New knowledge request indicators
    knowledge_terms = ("văn hóa", "lịch sử", "culture", "history", "truyền thống", "dân chài")

    has_place_topic = any(term in text for term in place_terms)
    has_action = any(term in text for term in action_terms)
    has_knowledge = any(term in text for term in knowledge_terms)

    # If it contains a place term and is long enough, treat it as a new request
    is_descriptive_place = has_place_topic and len(text.split()) >= 3

    return (has_place_topic and has_action) or has_knowledge or is_descriptive_place


def resolve_followup_before_tool_routing(
    state: AgentState,
    *,
    has_llm: bool = False,
    direct_answer: Callable[[str, list[dict[str, str]], str], str] = _default_direct_answer,
    clarify_message: Callable[[str], str] = _default_clarify_message,
) -> AgentState | None:
    """Resolve follow-ups before entering tool routing.

    Runs after _initial_state and before deterministic/LLM tool routing.
    Returns a fully-populated state when the follow-up can be answered
    from structured context, or None to proceed with normal routing.

    Decision routing:
    - structured_context → compose answer from prior context, skip tools
    - history_context    → use deterministic direct-answer path, skip tools
    - clarification_needed → return clarification message, skip tools
    - insufficient_context → proceed to normal routing
    """
    decision = state.get("followup_decision")
    prior = state.get("prior_context")

    if decision == "structured_context" and prior and prior.is_populated:
        state["response_text"] = compose_followup_answer(
            state["message"], prior, state["language"],
        )
        state["intent"] = "followup_contextual"
        state["places_response_ready"] = True
        state["fallback"] = False
        logger.debug(
            "agent.followup_resolved",
            session_id=state["session_id"],
            decision="structured_context",
        )
        return state

    if has_llm:
        # If the LLM is active, do NOT short-circuit general clarification_needed.
        # Let the LLM reason over the conversation history and choose the appropriate tools or responses natively.
        # Only allow history_context short-circuits (e.g. "?", "ví dụ") or very specific direct answers.
        if decision == "history_context":
            state["response_text"] = direct_answer(
                state["message"], state.get("history", []), state["language"],
            )
            state["intent"] = "followup_history"
            state["places_response_ready"] = True
            state["fallback"] = False
            return state
        return None

    if decision == "history_context":
        # Answerable from history alone — use direct-answer path, skip tools
        state["response_text"] = direct_answer(
            state["message"], state.get("history", []), state["language"],
        )
        state["intent"] = "followup_history"
        state["places_response_ready"] = True
        state["fallback"] = False
        return state

    if decision == "clarification_needed":
        # Distinguish between truly ambiguous pronouns and new requests.
        # If the message looks like a new place/knowledge request, let normal
        # routing handle it (insufficient_context path) rather than asking
        # for clarification about prior context.
        if _is_new_request(state["message"]):
            return None  # Proceed to normal routing
        state["response_text"] = clarify_message(state["language"])
        state["intent"] = "clarification"
        state["places_response_ready"] = True
        state["fallback"] = False
        return state

    # insufficient_context → proceed to normal routing
    return None
