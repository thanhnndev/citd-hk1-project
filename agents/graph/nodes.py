"""Node implementations for the Ham Ninh LangGraph."""

from __future__ import annotations

import hashlib
import inspect
import math
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from langgraph.types import interrupt
from langchain_core.runnables import RunnableConfig

from agents.graph.state import (
    AgentState,
    RouterOutput,
)
from agents.guardrails.input_guardrails import block_injection, reject_off_topic
from agents.guardrails.output_guardrails import verify_grounding
from agents.graph.routing import (
    _clarify_message,
    _direct_answer,
    _extract_suggestions,
    _fallback_action,
    _get_default_suggestions,
    _messages_for_llm,
)
import json
from app.models.rag import RAGChunk
from app.models.response import Citation
from agents.tools.retriever import citation_from_chunk

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# NodeServices — dependency injection container
# ---------------------------------------------------------------------------


@dataclass
class NodeServices:
    """Container for injected dependencies used by LLM-dependent nodes.

    The graph assembler (T02) constructs a ``NodeServices`` instance with
    the real OpenAI client, retriever, and places service, then calls
    ``configure_services(services)`` before compiling the graph.
    """

    llm_client: Any = None  # openai.AsyncOpenAI or None
    model: str = "gpt-4o-mini"
    retriever: Any = None  # Retriever or HybridRetriever or None
    places_service: Any = None  # PlaceRecommendationService or None
    cohere_reranker: Any = None  # CohereReranker or None (graceful degradation)
    llm_answer_service: Any = None  # LLMAnswerService or None
    semantic_cache: Any = None  # SemanticCache or None
    embedding_service: Any = None  # EmbeddingService or None


_default_services = NodeServices()


def configure_services(services: NodeServices) -> None:
    """Set the module-level NodeServices singleton.

    Called by the graph assembler (T02) before compiling the StateGraph.
    """
    global _default_services
    _default_services = services


def get_services() -> NodeServices:
    """Return the current module-level NodeServices singleton."""
    return _default_services


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_query(message: str) -> str:
    """Return a short SHA-256 hex digest (no raw text in logs)."""
    return hashlib.sha256(message.encode("utf-8")).hexdigest()[:16]


def requires_user_location_heuristic(message: str) -> bool:
    """Determine if a message requires location using simple substring search (no regex)."""
    text_lower = " ".join((message or "").strip().lower().split())
    if _has_explicit_search_area(text_lower):
        return False
    return _has_personal_location_reference(text_lower)


def _has_personal_location_reference(message: str) -> bool:
    """Return true only when the user asks relative to their current position."""
    text_lower = " ".join((message or "").strip().lower().split())
    keywords = [
        "gần tôi", "gần mình", "gần đây", "quanh đây", "quanh tôi", "quanh mình",
        "vị trí của tôi", "vị trí hiện tại", "near me", "nearby", "around here",
        "my location", "closest to me",
    ]
    return any(keyword in text_lower for keyword in keywords)


def _has_explicit_search_area(message: str) -> bool:
    """Return true when the user already named the destination/search area."""
    text_lower = " ".join((message or "").strip().lower().split())
    areas = [
        "hàm ninh", "ham ninh", "phú quốc", "phu quoc",
        "làng chài", "lang chai",
    ]
    return any(area in text_lower for area in areas)


def _resolve_needs_location(message: str, model_needs_location: bool) -> bool:
    """Keep the model decision, but do not ask for GPS when area is explicit."""
    text_lower = " ".join((message or "").strip().lower().split())
    if _has_explicit_search_area(text_lower):
        return False
    if _has_personal_location_reference(text_lower):
        return True
    return model_needs_location


def _has_domain_context(history: list[dict[str, str]]) -> bool:
    """Return true when recent conversation already established Ham Ninh tourism context."""
    recent = " ".join(str(item.get("content", "")) for item in history[-6:])
    text = " ".join(recent.lower().split())
    return _has_explicit_search_area(text) or _has_tourism_signal(text)


def _has_tourism_signal(message: str) -> bool:
    text = " ".join((message or "").strip().lower().split())
    terms = (
        "du lịch", "du lich", "tham quan", "lịch trình", "lich trinh",
        "địa điểm", "dia diem", "điểm đến", "diem den", "đi đâu", "di dau",
        "ăn uống", "an uong", "món ăn", "mon an", "hải sản", "hai san",
        "nhà hàng", "nha hang", "quán", "quan", "cà phê", "cafe",
        "khách sạn", "khach san", "homestay", "đường đi", "duong di",
        "chỉ đường", "chi duong", "bản đồ", "ban do", "route", "map",
        "restaurant", "hotel", "place", "places", "trip", "travel",
        "tourism", "attraction", "direction", "seafood",
    )
    return any(term in text for term in terms)


def _has_responsible_travel_signal(message: str) -> bool:
    text = " ".join((message or "").strip().lower().split())
    terms = (
        "người khuyết tật", "nguoi khuyet tat", "xe lăn", "xe lan",
        "tiếp cận", "tiep can", "accessibility", "accessible",
        "người già", "nguoi gia", "người lớn tuổi", "nguoi lon tuoi",
        "trẻ em", "tre em", "gia đình", "gia dinh", "sinh viên", "sinh vien",
        "ngân sách", "ngan sach", "giá rẻ", "gia re", "an toàn", "an toan",
        "nguy hiểm", "nguy hiem", "địa hình", "dia hinh", "môi trường",
        "moi truong", "địa phương", "dia phuong", "tôn trọng", "ton trong",
        "phù hợp", "phu hop", "nên tránh", "nen tranh", "safety", "budget",
        "disabled", "wheelchair", "elderly", "children", "terrain",
        "responsible", "local community",
    )
    return any(term in text for term in terms)


def _domain_refusal_message(language: str) -> str:
    if language == "vi":
        return (
            "Mình chỉ hỗ trợ tư vấn du lịch Hàm Ninh/Phú Quốc. "
            "Bạn có thể hỏi về địa điểm, đường đi, văn hóa, lịch trình, an toàn, "
            "ngân sách, khả năng tiếp cận hoặc du lịch có trách nhiệm."
        )
    return (
        "I only help with Ham Ninh/Phu Quoc travel advice. "
        "You can ask about places, directions, culture, itineraries, safety, "
        "budget, accessibility, or responsible tourism."
    )


def _domain_context_clarification_message(language: str) -> str:
    if language == "vi":
        return (
            "Bạn đang hỏi trong bối cảnh chuyến đi Hàm Ninh/Phú Quốc hay địa điểm nào cụ thể? "
            "Mình cần ngữ cảnh đó để tư vấn chính xác và có trách nhiệm."
        )
    return (
        "Are you asking in the context of a Ham Ninh/Phu Quoc trip or a specific place? "
        "I need that context to give careful travel advice."
    )


def _conversational_domain_action(
    message: str,
    history: list[dict[str, str]],
) -> Literal["allow", "clarify", "refuse"]:
    """Fallback-only domain gate when the semantic policy LLM is unavailable."""
    text = " ".join((message or "").strip().lower().split())
    if _has_explicit_search_area(text):
        return "allow"
    if _has_tourism_signal(text) and _has_domain_context(history):
        return "allow"
    if _has_responsible_travel_signal(text):
        return "allow" if _has_domain_context(history) else "clarify"
    if _has_tourism_signal(text):
        return "clarify"
    return "refuse"


def _requests_accessibility(message: str) -> bool:
    text = " ".join((message or "").strip().lower().split())
    return any(term in text for term in (
        "xe lăn", "xe lan", "wheelchair", "lối đi tiếp cận", "accessible entrance",
    ))


def _is_place_comparison_followup(message: str, state: AgentState) -> bool:
    if not state.get("last_places"):
        return False
    text = " ".join((message or "").strip().lower().split())
    return any(term in text for term in (
        "gần hơn", "gần nhất", "xa hơn", "nearer", "nearest", "closer",
        "rẻ hơn", "rẻ nhất", "cheaper", "cheapest",
        "đánh giá cao hơn", "rating cao hơn", "highest rated",
    ))


def _haversine_meters(
    origin: dict[str, float] | None,
    destination: dict[str, Any] | None,
) -> int | None:
    if not origin or not destination:
        return None
    try:
        lat1 = math.radians(float(origin["lat"]))
        lng1 = math.radians(float(origin["lng"]))
        lat2 = math.radians(float(destination["lat"]))
        lng2 = math.radians(float(destination["lng"]))
    except (KeyError, TypeError, ValueError):
        return None
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return round(6_371_000 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value)))


def _compare_previous_places(state: AgentState) -> dict[str, Any]:
    """Compare only the grounded places from the immediately preceding search."""
    language = state.get("language", "vi")
    origin = state.get("last_place_user_location") or state.get("user_location")
    places: list[dict[str, Any]] = []
    estimated_distance_used = False
    for raw in state.get("last_places") or []:
        item = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw) if isinstance(raw, dict) else None
        if item is None:
            continue
        distance = item.get("route_distance_meters")
        if not isinstance(distance, int):
            distance = _haversine_meters(origin, item.get("location"))
            if distance is not None:
                item["route_distance_meters"] = distance
                estimated_distance_used = True
        places.append(item)

    text = " ".join((state.get("message") or "").strip().lower().split())
    if any(term in text for term in ("rẻ hơn", "rẻ nhất", "cheaper", "cheapest")):
        ranked = [p for p in places if isinstance(p.get("price_level"), int)]
        ranked.sort(key=lambda p: p["price_level"])
        metric = "price"
    elif any(term in text for term in ("đánh giá cao hơn", "rating cao hơn", "highest rated")):
        ranked = [p for p in places if isinstance(p.get("rating"), (int, float))]
        ranked.sort(key=lambda p: p["rating"], reverse=True)
        metric = "rating"
    else:
        ranked = [p for p in places if isinstance(p.get("route_distance_meters"), int)]
        ranked.sort(key=lambda p: p["route_distance_meters"])
        metric = "distance"

    if len(ranked) < 2:
        response_text = (
            "Mình giữ nguyên các địa điểm vừa gợi ý, nhưng dữ liệu hiện có chưa đủ để so sánh tiêu chí này. "
            "Mình sẽ không thay chúng bằng một lượt tìm kiếm mới."
            if language == "vi"
            else "I kept the previous recommendations, but the available data is not enough for this comparison. "
            "I will not replace them with a new search."
        )
        return {"response_text": response_text, "places": places, "intent": "place_comparison"}

    best = ranked[0]
    name = best.get("display_name") or "Địa điểm đầu tiên"
    if metric == "distance":
        distance = int(best["route_distance_meters"])
        distance_text = f"{distance / 1000:.1f} km" if distance >= 1000 else f"{distance} m"
        distance_suffix = " (ước tính từ tọa độ hiện có)" if estimated_distance_used else ""
        response_text = (
            f"Trong các địa điểm vừa gợi ý, **{name}** gần hơn, khoảng {distance_text}{distance_suffix} từ vị trí đã dùng để tìm kiếm."
            if language == "vi"
            else f"Among the previous recommendations, **{name}** is closer, about {distance_text}{distance_suffix} from the search origin."
        )
    elif metric == "price":
        response_text = (
            f"Trong các địa điểm vừa gợi ý, **{name}** có mức giá thấp hơn theo metadata nhà cung cấp."
            if language == "vi"
            else f"Among the previous recommendations, **{name}** has the lower provider price level."
        )
    else:
        response_text = (
            f"Trong các địa điểm vừa gợi ý, **{name}** có điểm đánh giá cao hơn ({best['rating']:.1f}⭐)."
            if language == "vi"
            else f"Among the previous recommendations, **{name}** has the higher rating ({best['rating']:.1f}⭐)."
        )
    return {"response_text": response_text, "places": ranked, "intent": "place_comparison", "suggestions": []}


def _decision_followup_field(message: str) -> str | None:
    text = " ".join((message or "").strip().lower().split())
    if any(term in text for term in ("giá", "rẻ", "chi phí", "ngân sách", "price", "cost", "cheap", "budget")):
        return "price"
    if any(term in text for term in ("xe lăn", "xe lan", "khuyết tật", "tiếp cận", "accessible", "wheelchair", "disability")):
        return "accessibility"
    if any(term in text for term in ("địa hình", "đường đi", "bề mặt", "terrain", "slope", "surface")):
        return "terrain"
    if any(term in text for term in ("an toàn", "nguy hiểm", "rủi ro", "safe", "safety", "dangerous", "risk")):
        return "safety"
    return None


def _has_deictic_place_reference(message: str) -> bool:
    text = " ".join((message or "").strip().lower().split())
    return any(term in text for term in (
        "đó", "chỗ đó", "nơi đó", "địa điểm đó", "ở đó", "đến đó", "tới đó",
        "này", "chỗ này", "nơi này", "địa điểm này", "ở đây",
        "that place", "there", "this place",
    ))


def _clarify_decision_followup_without_context(state: AgentState) -> dict[str, Any] | None:
    """Ask for the target place when a decision-sensitive follow-up has no place context."""
    if state.get("last_places"):
        return None
    field = _decision_followup_field(state.get("message", ""))
    if field is None or not _has_deictic_place_reference(state.get("message", "")):
        return None

    language = state.get("language", "vi")
    response_text = (
        "Bạn đang hỏi về địa điểm nào? Mình chưa có địa điểm trước đó trong cuộc trò chuyện để hiểu \"đó\" là nơi nào. "
        "Bạn gửi tên địa điểm cụ thể, mình sẽ tư vấn theo dữ liệu hiện có và nói rõ phần nào chưa được xác nhận."
        if language == "vi"
        else "Which place do you mean? I do not have a previous place in this conversation to resolve that reference. "
        "Send the specific place name and I will advise using the available data and state what is not confirmed."
    )
    return {
        "response_text": response_text,
        "places": [],
        "intent": "place_decision_followup",
        "suggestions": [],
    }


def _resolve_last_place_reference(message: str, places: list[dict[str, Any]]) -> dict[str, Any] | None:
    text = " ".join((message or "").strip().lower().split())
    best: dict[str, Any] | None = None
    best_score = 0
    for place in places:
        name = str(place.get("display_name") or "")
        normalized = " ".join(name.lower().split())
        if normalized and normalized in text:
            return place
        tokens = [token for token in normalized.split() if len(token) > 2]
        score = sum(1 for token in tokens if token in text)
        if score > best_score:
            best = place
            best_score = score
    if best is not None and best_score >= 2:
        return best
    if len(places) == 1 and any(term in text for term in ("đó", "này", "kia", "that", "this", "there")):
        return places[0]
    return None


def _answer_place_decision_followup(state: AgentState) -> dict[str, Any] | None:
    """Answer decision-sensitive follow-ups from last place context instead of re-searching."""
    field = _decision_followup_field(state.get("message", ""))
    if field is None:
        return None

    places: list[dict[str, Any]] = []
    for raw in state.get("last_places") or []:
        item = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw) if isinstance(raw, dict) else None
        if item is not None:
            places.append(item)
    if not places:
        return None

    language = state.get("language", "vi")
    place = _resolve_last_place_reference(state.get("message", ""), places)
    if place is None:
        names = "; ".join(str(p.get("display_name") or "địa điểm") for p in places[:3])
        response_text = (
            f"Bạn đang hỏi về địa điểm nào trong các nơi vừa gợi ý? Một vài lựa chọn: {names}."
            if language == "vi"
            else f"Which previously recommended place do you mean? Options include: {names}."
        )
        return {"response_text": response_text, "places": places, "intent": "place_decision_followup", "suggestions": []}

    name = str(place.get("display_name") or "địa điểm này")
    explanation = place.get("explanation") if isinstance(place.get("explanation"), dict) else {}

    if field == "price":
        price_level = place.get("price_level")
        if isinstance(price_level, int):
            response_text = (
                f"Về **{name}**: dữ liệu nhà cung cấp có `price_level={price_level}`. Đây chỉ là tín hiệu mức giá, không phải giá thực tế; bạn vẫn nên kiểm tra giá và phụ phí trước khi quyết định."
                if language == "vi"
                else f"About **{name}**: provider data has `price_level={price_level}`. This is only a price-level signal, not the actual current price; verify prices and extra fees before deciding."
            )
        else:
            response_text = (
                f"Về **{name}**: dữ liệu hiện có chưa xác nhận giá thực tế hoặc mức chi phí. Nếu tài chính hạn chế, bạn nên kiểm tra giá trước, hỏi phụ phí, và ưu tiên hoạt động không bắt buộc dùng dịch vụ."
                if language == "vi"
                else f"About **{name}**: the current data does not confirm actual prices or cost level. If budget is limited, verify prices first, ask about extra fees, and prefer activities that do not require paid services."
            )
    elif field == "accessibility":
        note = str(explanation.get("accessibility_note") or "")
        if "verifies a wheelchair-accessible entrance" in note:
            response_text = (
                f"Về **{name}**: metadata nhà cung cấp có xác nhận lối vào cho xe lăn. Tuy vậy, dữ liệu vẫn chưa đủ để kết luận về bề mặt đường, độ dốc, nhà vệ sinh hoặc khoảng cách di chuyển; bạn nên gọi xác nhận trước khi đi."
                if language == "vi"
                else f"About **{name}**: provider metadata verifies a wheelchair-accessible entrance. It still does not fully confirm surface, slope, restrooms, or walking distance; verify directly before going."
            )
        elif "reports no wheelchair-accessible entrance" in note:
            response_text = (
                f"Về **{name}**: metadata nhà cung cấp báo không có lối vào cho xe lăn. Nếu đi cùng người dùng xe lăn hoặc người di chuyển khó khăn, nên chọn phương án khác hoặc gọi xác nhận trực tiếp."
                if language == "vi"
                else f"About **{name}**: provider metadata reports no wheelchair-accessible entrance. If traveling with a wheelchair user or someone with limited mobility, choose another option or verify directly."
            )
        else:
            response_text = (
                f"Về **{name}**: dữ liệu hiện có chưa xác nhận lối vào xe lăn, bề mặt đường, độ dốc hoặc nhà vệ sinh phù hợp. Nếu đi cùng người khuyết tật, bạn nên gọi xác nhận trực tiếp và hỏi rõ các điểm này trước khi đi."
                if language == "vi"
                else f"About **{name}**: current data does not confirm wheelchair entrance, surface, slope, or accessible restrooms. If traveling with a disabled visitor, verify these details directly before going."
            )
    elif field == "terrain":
        response_text = (
            f"Về **{name}**: dữ liệu hiện có chưa có thông tin địa hình như bậc thang, độ dốc, bề mặt đường hoặc khoảng cách đi bộ. Mình không nên kết luận là dễ đi hay khó đi khi chưa có bằng chứng đó."
            if language == "vi"
            else f"About **{name}**: current data does not include terrain details such as steps, slope, walking surface, or walking distance. I should not conclude whether it is easy or difficult without that evidence."
        )
    else:
        response_text = (
            f"Về **{name}**: dữ liệu hiện có chưa đủ để đánh giá mức độ an toàn theo thời tiết, thủy triều, đông đúc hoặc điều kiện tại chỗ. Bạn nên kiểm tra tình hình thực tế trước khi quyết định."
            if language == "vi"
            else f"About **{name}**: current data is not enough to assess safety for weather, tide, crowding, or on-site conditions. Verify current conditions before deciding."
        )

    return {"response_text": response_text, "places": places, "intent": "place_decision_followup", "suggestions": []}


# ---------------------------------------------------------------------------
# 1. input_guardrails_node (REAL)
# ---------------------------------------------------------------------------


async def input_guardrails_node(state: AgentState) -> dict[str, Any]:
    """Run input guardrails: prompt injection blocking + topic rejection.

    Reads:
        - ``state["message"]``
    Writes:
        - ``guardrail_flags`` — dict with ``injection`` and ``off_topic`` verdicts
        - ``response_text`` — friendly rejection message when blocked
    """
    t0 = time.perf_counter()
    message = state.get("message", "")
    query_hash = _hash_query(message)
    session_id = state.get("session_id", "")

    logger.info(
        "graph.node_enter",
        node="input_guardrails",
        session_id=session_id,
        query_hash=query_hash,
    )

    flags: dict[str, Any] = dict(state.get("guardrail_flags") or {})

    # --- Injection check ---
    injection_result = block_injection(message)
    flags["injection"] = {
        "verdict": injection_result.verdict,
        "reason": injection_result.reason,
        "severity": injection_result.severity,
    }

    if injection_result.verdict == "blocked":
        language = state.get("language", "vi")
        blocked_msg = (
            "Xin lỗi, mình không thể xử lý yêu cầu này."
            if language == "vi"
            else "Sorry, I cannot process this request."
        )
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="input_guardrails",
            session_id=session_id,
            verdict="blocked",
            reason="injection_detected",
            duration_ms=elapsed,
        )
        return {
            "guardrail_flags": flags,
            "response_text": blocked_msg,
            "intent": "blocked",
            "blocked": True,
            "run_status": "failed-terminal",
        }

    # --- Off-topic check ---
    services = get_services()
    topic_result = await reject_off_topic(message, services.llm_client, services.model)
    flags["off_topic"] = {
        "verdict": topic_result.verdict,
        "reason": topic_result.reason,
        "severity": topic_result.severity,
    }

    if topic_result.verdict == "blocked":
        language = state.get("language", "vi")
        off_topic_msg = (
            "Mình chỉ hỗ trợ thông tin du lịch Hàm Ninh. "
            "Bạn hỏi về địa điểm, đường đi, văn hóa/lịch sử hoặc gợi ý lịch trình nhé!"
            if language == "vi"
            else "I only assist with Ham Ninh tourism. "
            "Ask about places, directions, culture/history, or trip planning!"
        )
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="input_guardrails",
            session_id=session_id,
            verdict="blocked",
            reason="off_topic",
            duration_ms=elapsed,
        )
        return {
            "guardrail_flags": flags,
            "response_text": off_topic_msg,
            "intent": "off_topic",
            "blocked": True,
            "run_status": "failed-terminal",
        }

    elapsed = round((time.perf_counter() - t0) * 1000, 3)
    logger.info(
        "graph.node_exit",
        node="input_guardrails",
        session_id=session_id,
        verdict="pass",
        duration_ms=elapsed,
    )
    return {"guardrail_flags": flags}


# ---------------------------------------------------------------------------
# 2. intent_router_node (REAL)
# ---------------------------------------------------------------------------

def _checkpoint_history(state: AgentState) -> list[dict[str, str]]:
    """Return prior chat turns from checkpointed messages, excluding current user turn."""
    explicit_history = state.get("history") or []
    if explicit_history:
        return explicit_history

    current_message = state.get("message", "")
    raw_messages = state.get("messages") or []
    history: list[dict[str, str]] = []
    for item in raw_messages:
        role = None
        content = None
        if isinstance(item, dict):
            role = item.get("role")
            content = item.get("content")
        elif hasattr(item, "type") and hasattr(item, "content"):
            content = item.content
            if item.type == "human":
                role = "user"
            elif item.type == "ai":
                role = "assistant"
            else:
                role = item.type
        
        if role not in {"user", "assistant"} or not content:
            continue
        if role == "user" and content == current_message:
            continue
        history.append({"role": role, "content": str(content)})
    return history[-12:]


_INTENT_ROUTER_SYSTEM_PROMPT = """\
You are an intent classifier for the Ham Ninh tourism assistant.
Classify the user's message into one of these intents:
- cultural_query: questions about culture, history, fishing life, local food background
- food_culture: specifically about food traditions, recipes, local specialties
- restaurant_search: finding restaurants, cafes, hotels, places, directions, maps
  Also use this for requests asking where to go with children/family, because
  concrete venue suitability must be checked against provider place data.
- navigation: asking for directions, routes, maps
- conversational: greetings, thanks, capability questions, simple acknowledgments
- unknown: anything that does not fit the above

Also determine:
- confidence: your confidence in the classification (0.0 to 1.0)
- is_followup: whether the message references prior conversation context
- needs_location: whether the query requires the user's current GPS.
  Set true for local/deictic requests such as "near me", "nearby", "nearest",
  "around here", "gần đây", "gần tôi", "quanh đây", "từ vị trí của tôi",
  or "give me directions from where I am".
  Set false for route questions that already include an explicit origin, e.g.
  "Từ Dương Đông đi Hàm Ninh thế nào?" because no user GPS is needed.
Examples:
- "Tìm quán hải sản gần đây" -> restaurant_search, high confidence, needs_location=true
- "Có quán ăn nào gần tôi không?" -> restaurant_search, high confidence, needs_location=true
- "Tìm nhà hàng hải sản ở Hàm Ninh" -> restaurant_search, high confidence, needs_location=false
- "Đi với trẻ em nên ghé đâu?" -> restaurant_search, high confidence, needs_location=false
"""


async def intent_router_node(state: AgentState) -> dict[str, Any]:
    """Classify user intent via LLM structured output or heuristic fallback.

    When the LLM client is available, calls OpenAI with
    ``response_format=RouterOutput`` for structured classification.
    Falls back to deterministic heuristic routing when unavailable.

    Reads:
        - ``state["message"]``, ``state["history"]``, ``state["language"]``
    Writes:
        - ``intent``, ``intent_confidence``, ``needs_location``
    """
    t0 = time.perf_counter()
    message = state.get("message", "")
    history = _checkpoint_history(state)
    language = state.get("language", "vi")
    session_id = state.get("session_id", "")
    query_hash = _hash_query(message)

    logger.info(
        "graph.node_enter",
        node="intent_router",
        session_id=session_id,
        query_hash=query_hash,
    )

    if _is_place_comparison_followup(message, state):
        return {
            "intent": "restaurant_search",
            "intent_confidence": 1.0,
            "is_followup": True,
            "needs_location": False,
            "current_step": "places",
        }

    services = get_services()
    client = services.llm_client

    # --- LLM path ---
    if client is not None and RouterOutput is not None:
        try:
            messages = [
                {"role": "system", "content": _INTENT_ROUTER_SYSTEM_PROMPT},
            ]
            # Include recent history for follow-up detection
            for item in (history or [])[-4:]:
                if item.get("role") in {"user", "assistant"} and item.get("content"):
                    messages.append({"role": item["role"], "content": item["content"]})
            original_message = message
            messages.append({"role": "user", "content": original_message})

            completion = await client.chat.completions.parse(
                model=services.model,
                messages=messages,
                response_format=RouterOutput,
                max_completion_tokens=128,
            )
            message = completion.choices[0].message
            if message.parsed:
                intent_label = message.parsed.intent
                confidence = float(message.parsed.confidence)
                is_followup = bool(message.parsed.is_followup)
                model_needs_location = bool(message.parsed.needs_location)
                needs_location = _resolve_needs_location(original_message, model_needs_location)
            else:
                # Fallback to heuristic if model refused or parsing failed
                raise ValueError(f"LLM refused or failed to parse: {message.refusal}")

            elapsed = round((time.perf_counter() - t0) * 1000, 3)
            logger.info(
                "graph.node_exit",
                node="intent_router",
                session_id=session_id,
                intent=intent_label,
                confidence=confidence,
                model_needs_location=model_needs_location,
                enforced_needs_location=needs_location,
                mode="llm",
                duration_ms=elapsed,
            )
            return {
                "intent": intent_label,
                "intent_confidence": confidence,
                "is_followup": is_followup,
                "needs_location": needs_location,
                "current_step": (
                    "knowledge"
                    if intent_label in {"cultural_query", "food_culture"}
                    else "places"
                    if intent_label in {"restaurant_search", "navigation"}
                    else "conversational"
                ),
            }

        except Exception as exc:
            logger.warning(
                "graph.node_error",
                node="intent_router",
                session_id=session_id,
                error_type=type(exc).__name__,
                error=str(exc),
                mode="llm_failed_falling_back",
            )

    # --- Heuristic fallback ---
    action = _fallback_action(message, history)
    if action == "direct":
        intent_label = "conversational"
        confidence = 0.95
    elif action == "clarify":
        intent_label = "conversational"
        confidence = 0.6
    else:
        # Simple keyword-based heuristic
        text_lower = (message or "").lower()
        if any(term in text_lower for term in (
            "văn hóa", "văn hoá", "lịch sử", "culture", "history",
            "làng chài", "fishing", "nghề biển",
        )):
            intent_label = "cultural_query"
            confidence = 0.7
        elif any(term in text_lower for term in (
            "quán", "nhà hàng", "restaurant", "hotel", "homestay",
            "cà phê", "cafe", "tìm", "find", "search", "gần", "nearby",
            "trẻ em", "trẻ nhỏ", "gia đình", "children", "kids", "family",
            "ghé đâu", "đi đâu", "where should",
        )):
            intent_label = "restaurant_search"
            confidence = 0.7
        elif any(term in text_lower for term in (
            "đường", "direction", "route", "map", "bản đồ", "chỉ đường",
        )):
            intent_label = "navigation"
            confidence = 0.65
        elif any(term in text_lower for term in (
            "món ăn", "đặc sản", "ẩm thực", "food", "specialty",
        )):
            intent_label = "food_culture"
            confidence = 0.65
        else:
            intent_label = "unknown"
            confidence = 0.4

    needs_location = requires_user_location_heuristic(message)

    elapsed = round((time.perf_counter() - t0) * 1000, 3)
    logger.info(
        "graph.node_exit",
        node="intent_router",
        session_id=session_id,
        intent=intent_label,
        confidence=confidence,
        mode="heuristic",
        duration_ms=elapsed,
    )
    return {
        "intent": intent_label,
        "intent_confidence": confidence,
        "is_followup": bool(history),
        "needs_location": needs_location,
        "current_step": (
            "knowledge"
            if intent_label in {"cultural_query", "food_culture"}
            else "places"
            if intent_label in {"restaurant_search", "navigation"}
            else "conversational"
        ),
    }


# ---------------------------------------------------------------------------
# 3. conversational_node
# ---------------------------------------------------------------------------


async def conversational_node(state: AgentState) -> dict[str, Any]:
    """Handle conversational intents: greetings, capability questions, clarifications.

    Uses deterministic helpers from ``routing.py`` for direct answers.
    When the LLM client is available and the action is ``llm``, calls the
    LLM for a natural conversational response.

    Reads:
        - ``state["message"]``, ``state["history"]``, ``state["language"]``
    Writes:
        - ``response_text``, ``suggestions``, ``intent``
    """
    t0 = time.perf_counter()
    message = state.get("message", "")
    history = _checkpoint_history(state)
    language = state.get("language", "vi")
    session_id = state.get("session_id", "")

    logger.info(
        "graph.node_enter",
        node="conversational",
        session_id=session_id,
    )

    action = _fallback_action(message, history)

    # --- Direct answer (greetings, capability questions) ---
    if action == "direct":
        response_text = _direct_answer(message, history, language)
        suggestions = _get_default_suggestions(
            intent="conversational",
            language=language,
        )
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="conversational",
            session_id=session_id,
            action="direct",
            duration_ms=elapsed,
        )
        return {
            "response_text": response_text,
            "suggestions": suggestions,
            "intent": "conversational",
        }

    # --- Clarification ---
    if action == "clarify":
        response_text = _clarify_message(language)
        suggestions = _get_default_suggestions(
            intent="clarification",
            language=language,
        )
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="conversational",
            session_id=session_id,
            action="clarify",
            duration_ms=elapsed,
        )
        return {
            "response_text": response_text,
            "suggestions": suggestions,
            "intent": "clarification",
        }

    domain_action = _conversational_domain_action(message, history)
    if domain_action in {"clarify", "refuse"}:
        response_text = (
            _domain_context_clarification_message(language)
            if domain_action == "clarify"
            else _domain_refusal_message(language)
        )
        intent = "clarification" if domain_action == "clarify" else "off_topic"
        suggestions = _get_default_suggestions(
            intent=intent,
            language=language,
            fallback=True,
        )
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="conversational",
            session_id=session_id,
            action=f"domain_{domain_action}",
            duration_ms=elapsed,
        )
        return {
            "response_text": response_text,
            "suggestions": suggestions,
            "intent": intent,
        }

    # --- LLM path for general conversational ---
    services = get_services()
    client = services.llm_client
    if client is not None:
        try:
            messages = _messages_for_llm(
                message=message,
                history=history,
                language=language,
            )
            writer = None
            try:
                from langgraph.config import get_stream_writer
                writer = get_stream_writer()
            except Exception:
                writer = None

            if writer is not None:
                stream = await client.chat.completions.create(
                    model=services.model,
                    messages=messages,
                    max_completion_tokens=512,
                    stream=True,
                )
                content_parts: list[str] = []
                pending = ""
                suggestions_marker = "[SUGGESTIONS]"
                marker_seen = False
                async for chunk in stream:
                    token = chunk.choices[0].delta.content or ""
                    if token:
                        content_parts.append(token)
                        if marker_seen:
                            continue
                        pending += token
                        if suggestions_marker in pending:
                            visible, _ = pending.split(suggestions_marker, 1)
                            if visible:
                                writer({"type": "token", "content": visible})
                            pending = ""
                            marker_seen = True
                            continue
                        safe_length = max(0, len(pending) - len(suggestions_marker) + 1)
                        if safe_length:
                            writer({"type": "token", "content": pending[:safe_length]})
                            pending = pending[safe_length:]
                if pending and not marker_seen:
                    writer({"type": "token", "content": pending})
                content = "".join(content_parts)
            else:
                completion = await client.chat.completions.create(
                    model=services.model,
                    messages=messages,
                    max_completion_tokens=512,
                )
                content = completion.choices[0].message.content or ""
            msg_text, suggestions = _extract_suggestions(content)
            if not msg_text:
                msg_text = _clarify_message(language)
            if not suggestions:
                suggestions = _get_default_suggestions(
                    intent="conversational",
                    language=language,
                )
            elapsed = round((time.perf_counter() - t0) * 1000, 3)
            logger.info(
                "graph.node_exit",
                node="conversational",
                session_id=session_id,
                action="llm",
                duration_ms=elapsed,
            )
            return {
                "response_text": msg_text,
                "suggestions": suggestions,
                "intent": state.get("intent") or "conversational",
            }
        except Exception as exc:
            logger.warning(
                "graph.node_error",
                node="conversational",
                session_id=session_id,
                error_type=type(exc).__name__,
                error=str(exc),
                mode="llm_failed_falling_back",
            )

    # --- Fallback: deterministic response ---
    response_text = _direct_answer(message, history, language)
    if not response_text:
        response_text = _clarify_message(language)
    suggestions = _get_default_suggestions(
        intent="conversational",
        language=language,
        fallback=True,
    )
    elapsed = round((time.perf_counter() - t0) * 1000, 3)
    logger.info(
        "graph.node_exit",
        node="conversational",
        session_id=session_id,
        action="fallback",
        duration_ms=elapsed,
    )
    return {
        "response_text": response_text,
        "suggestions": suggestions,
        "intent": state.get("intent") or "conversational",
    }


# ---------------------------------------------------------------------------
# 5. output_guardrails_node (REAL)
# ---------------------------------------------------------------------------


async def output_guardrails_node(state: AgentState) -> dict[str, Any]:
    """Verify that the response text is grounded in source material.

    Reads:
        - ``state["response_text"]``, ``state["citations"]``
    Writes:
        - ``guardrail_flags`` — updated with ``output_grounding`` verdict
    """
    t0 = time.perf_counter()
    session_id = state.get("session_id", "")
    response_text = state.get("response_text", "")

    logger.info(
        "graph.node_enter",
        node="output_guardrails",
        session_id=session_id,
    )

    flags: dict[str, Any] = dict(state.get("guardrail_flags") or {})

    # Skip document-grounding for responses that are not RAG document answers.
    # Place/map answers are grounded by provider place data, not citations.
    intent = state.get("intent")
    if intent in (
        "blocked", "off_topic", "conversational", "clarification",
        "restaurant_search", "navigation", "place_comparison",
    ):
        flags["output_grounding"] = {
            "verdict": "skipped",
            "reason": f"intent_{intent}",
        }
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="output_guardrails",
            session_id=session_id,
            verdict="skipped",
            reason=f"intent_{intent}",
            duration_ms=elapsed,
        )
        update: dict[str, Any] = {"guardrail_flags": flags}
        if response_text:
            update["messages"] = [{"role": "assistant", "content": response_text}]
        return update

    citations = state.get("citations", [])
    services = get_services()
    grounding_result = await verify_grounding(
        response_text,
        citations or None,
        services.llm_client,
        services.model,
        places=state.get("places", []),
    )

    flags["output_grounding"] = {
        "verdict": grounding_result.verdict,
        "reason": grounding_result.reason,
        "severity": grounding_result.severity,
        "details": grounding_result.details or "",
    }

    elapsed = round((time.perf_counter() - t0) * 1000, 3)
    logger.info(
        "graph.node_exit",
        node="output_guardrails",
        session_id=session_id,
        verdict=grounding_result.verdict,
        reason=grounding_result.reason,
        duration_ms=elapsed,
    )
    update: dict[str, Any] = {"guardrail_flags": flags}
    if response_text:
        update["messages"] = [{"role": "assistant", "content": response_text}]
    return update


# ---------------------------------------------------------------------------
# 6. rag_agent_node (REAL — hybrid retrieval + Cohere rerank + LLM answer)
# ---------------------------------------------------------------------------


async def rag_agent_node(state: AgentState) -> dict[str, Any]:
    """RAG agent node: retrieve, rerank, and generate a grounded answer.

    Pipeline:
        1. Retrieve top-10 chunks via the injected retriever (hybrid or BM25).
        2. Rerank with Cohere cross-encoder (top-5) when available.
        3. Build citations from the reranked chunks.
        4. Generate a grounded answer via LLMAnswerService when available.
        5. Fall back to deterministic text on any LLM or retrieval failure.

    Reads:
        - ``state["message"]``, ``state["rewritten_query"]``,
          ``state["language"]``, ``state["session_id"]``
    Writes:
        - ``knowledge_chunks``, ``citations``, ``response_text``,
          ``knowledge_response_ready``
    """
    t0 = time.perf_counter()
    message = state.get("message", "")
    language = state.get("language", "vi")
    session_id = state.get("session_id", "")

    logger.info(
        "graph.node_enter",
        node="rag_agent",
        session_id=session_id,
    )

    services = get_services()
    retriever = services.retriever
    cohere_reranker = services.cohere_reranker
    llm_answer_service = services.llm_answer_service

    # Check semantic cache first
    query_embedding = None
    if services.semantic_cache is not None and services.embedding_service is not None:
        try:
            embeddings = await services.embedding_service.embed_texts([message])
            query_embedding = embeddings[0] if embeddings else None
            if query_embedding is not None:
                cached = await services.semantic_cache.lookup(message, query_embedding)
                if cached is not None:
                    try:
                        cache_data = json.loads(cached)
                        cached_response = cache_data.get("response_text", "")
                        cached_chunks_data = cache_data.get("knowledge_chunks", [])
                        cached_citations_data = cache_data.get("citations", [])
                        
                        cached_chunks = [RAGChunk.model_validate(c) for c in cached_chunks_data]
                        cached_citations = [Citation.model_validate(c) for c in cached_citations_data]
                    except Exception:
                        # Fallback for old simple cache entries
                        cached_response = cached
                        cached_chunks = [RAGChunk(
                            chunk_id="cache_hit", source_id="semantic_cache", title="Semantic Cache Hit",
                            url="", domain="cache", source_type="cache", reliability="low", language=language,
                            location="", text=cached, chunk_index=0, total_chunks=1,
                        )]
                        cached_citations = [Citation(
                            source="Semantic Cache Hit",
                            url="",
                            snippet=cached[:200]
                        )]
                    
                    elapsed = round((time.perf_counter() - t0) * 1000, 3)
                    logger.info(
                        "graph.node_exit",
                        node="rag_agent",
                        session_id=session_id,
                        mode="semantic_cache_hit",
                        chunk_count=len(cached_chunks),
                        citation_count=len(cached_citations),
                        duration_ms=elapsed,
                    )
                    return {
                        "knowledge_chunks": cached_chunks,
                        "citations": cached_citations,
                        "response_text": cached_response,
                        "run_status": "gathering",
                        "current_step": "knowledge",
                        "tool_receipts": [{
                            "tool": "semantic_cache",
                            "status": "hit",
                            "result_count": len(cached_chunks),
                        }],
                    }
        except Exception as exc:
            logger.warning(
                "rag_agent.semantic_cache_failed",
                error=str(exc),
                session_id=session_id,
            )

    # ------------------------------------------------------------------
    # Step 1: Retrieve top-10 chunks
    # ------------------------------------------------------------------
    chunks: list[Any] = []

    if retriever is not None:
        try:
            result = retriever.search(message, top_k=10)
            # Handle both sync (Retriever) and async (HybridRetriever)
            if inspect.isawaitable(result):
                result = await result
            chunks = list(result.chunks) if result else []
        except Exception as exc:
            logger.warning(
                "rag_agent.retrieve_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                session_id=session_id,
            )
            chunks = []

    # ------------------------------------------------------------------
    # Step 2: Rerank with Cohere cross-encoder (top-5)
    # ------------------------------------------------------------------
    if cohere_reranker is not None and chunks:
        try:
            chunks = await cohere_reranker.rerank(message, chunks, top_n=5)
        except Exception as exc:
            # CohereReranker already handles its own graceful degradation,
            # but catch any unexpected failure here too.
            logger.warning(
                "rag_agent.rerank_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                session_id=session_id,
            )
            chunks = chunks[:5]

    # ------------------------------------------------------------------
    # Step 3: Build citations from chunks
    # ------------------------------------------------------------------
    citations: list[Any] = [citation_from_chunk(c) for c in chunks]

    # ------------------------------------------------------------------
    # Step 4: Generate grounded answer via LLM
    # ------------------------------------------------------------------
    response_text = ""
    mode = "no_llm"

    if llm_answer_service is not None and chunks:
        try:
            writer = None
            try:
                from langgraph.config import get_stream_writer
                writer = get_stream_writer()
            except Exception:
                writer = None

            stream_answer = getattr(llm_answer_service, "answer_stream", None)
            if writer is not None and callable(stream_answer):
                parts: list[str] = []
                async for token in stream_answer(
                    chunks=chunks,
                    citations=citations,
                    query=message,
                    language=language,
                    session_id=session_id,
                ):
                    parts.append(token)
                    writer({"type": "token", "content": token})
                response_text = "".join(parts)
                mode = "llm_stream"
            else:
                response = await llm_answer_service.answer(
                    chunks=chunks,
                    citations=citations,
                    query=message,
                    language=language,
                    session_id=session_id,
                )
                response_text = response.message
                mode = "llm"
        except Exception as exc:
            logger.warning(
                "rag_agent.llm_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                fallback=True,
                session_id=session_id,
            )
            response_text = ""
            mode = "llm_failed"

    # ------------------------------------------------------------------
    # Step 5: Fallback response when LLM unavailable or failed
    # ------------------------------------------------------------------
    if not response_text:
        if chunks:
            # Deterministic fallback: summarize first chunk(s)
            if language == "vi":
                response_text = (
                    f"Dựa trên thông tin có sẵn, đây là điều mình tìm được:\n\n"
                    f"**{chunks[0].title}**: {chunks[0].text[:300]}"
                )
                if len(chunks) > 1:
                    response_text += f"\n\n**{chunks[1].title}**: {chunks[1].text[:200]}"
            else:
                response_text = (
                    f"Based on available information, here is what I found:\n\n"
                    f"**{chunks[0].title}**: {chunks[0].text[:300]}"
                )
                if len(chunks) > 1:
                    response_text += f"\n\n**{chunks[1].title}**: {chunks[1].text[:200]}"
            mode = "deterministic"
        else:
            # No chunks available at all
            if language == "vi":
                response_text = (
                    "Mình chưa có thông tin cụ thể về khoản này, "
                    "nhưng bạn có thể hỏi thêm về văn hóa, lịch sử, "
                    "hoặc các địa điểm ở Hàm Ninh nhé!"
                )
            else:
                response_text = (
                    "I don't have specific information about this yet, "
                    "but feel free to ask about Ham Ninh's culture, history, "
                    "or places!"
                )
            mode = "no_chunks"

    # Store in semantic cache if enabled and response was successfully generated
    if (
        services.semantic_cache is not None
        and services.embedding_service is not None
        and response_text
        and mode in ("llm", "llm_stream", "deterministic")
    ):
        try:
            if query_embedding is None:
                embeddings = await services.embedding_service.embed_texts([message])
                query_embedding = embeddings[0] if embeddings else None
            if query_embedding is not None:
                cache_data = {
                    "response_text": response_text,
                    "knowledge_chunks": [c.model_dump() for c in chunks],
                    "citations": [cit.model_dump() for cit in citations],
                }
                await services.semantic_cache.store(
                    query=message,
                    query_embedding=query_embedding,
                    response=json.dumps(cache_data),
                )
        except Exception as exc:
            logger.warning(
                "rag_agent.semantic_cache_store_failed",
                error=str(exc),
                session_id=session_id,
            )

    elapsed = round((time.perf_counter() - t0) * 1000, 3)
    logger.info(
        "graph.node_exit",
        node="rag_agent",
        session_id=session_id,
        mode=mode,
        chunk_count=len(chunks),
        citation_count=len(citations),
        duration_ms=elapsed,
    )
    return {
        "knowledge_chunks": chunks,
        "citations": citations,
        "response_text": response_text,
        "run_status": "gathering",
        "current_step": "knowledge",
        "tool_receipts": [{
            "tool": "knowledge_retriever",
            "status": mode,
            "result_count": len(chunks),
        }],
    }


# ---------------------------------------------------------------------------
# 6. maps_agent_node
# ---------------------------------------------------------------------------


async def maps_agent_node(state: AgentState, config: RunnableConfig = None) -> dict[str, Any]:
    """Maps agent node: call PlaceRecommendationService for place recommendations.

    Calls the injected PlaceRecommendationService to retrieve fairness-ranked
    places with score_breakdown. Handles location consent and service failures
    gracefully.

    Reads:
        - ``state["message"]`` — user query text
        - ``state["user_location"]`` — optional dict with lat/lng
        - ``state["language"]`` — language code (default "vi")
        - ``state["session_id"]`` — session identifier
        - ``state["needs_location"]`` — whether location is required
    Writes:
        - ``places`` — list of place dicts with score_breakdown
        - ``response_text`` — natural language response message
    """
    t0 = time.perf_counter()
    session_id = state.get("session_id", "")
    message = state.get("message", "")
    language = state.get("language", "vi")
    needs_location = state.get("needs_location", False)

    # Best practice: Retrieve static configuration parameters from RunnableConfig if available,
    # falling back to AgentState for backward compatibility.
    configurable = config.get("configurable", {}) if config else {}
    user_location = configurable.get("user_location") or state.get("user_location")
    if not needs_location:
        user_location = None
    budget_filter = configurable.get("budget_filter") or state.get("budget_filter")
    accessibility_required = bool(
        configurable.get("accessibility_required", state.get("accessibility_required", False))
        or _requests_accessibility(message)
    )

    logger.info(
        "graph.node_enter",
        node="maps_agent",
        session_id=session_id,
        mode="place_recommendation",
    )

    if _is_place_comparison_followup(message, state):
        return _compare_previous_places(state)

    missing_context_followup = _clarify_decision_followup_without_context(state)
    if missing_context_followup is not None:
        return missing_context_followup

    decision_followup = _answer_place_decision_followup(state)
    if decision_followup is not None:
        return decision_followup

    # Location consent: use interrupt() pattern per LangGraph docs
    # Frontend will detect interrupt, request geolocation, and resume with Command(resume=user_location)
    if needs_location and user_location is None:
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="maps_agent",
            session_id=session_id,
            mode="location_interrupt",
            duration_ms=elapsed,
        )
        # Pause graph and request location from frontend
        user_location = interrupt({
            "type": "location_request",
            "message": (
                "Để gợi ý địa điểm phù hợp gần bạn, mình cần biết vị trí hiện tại. "
                "Trình duyệt sẽ yêu cầu quyền truy cập vị trí."
                if language == "vi"
                else "To recommend places near you, I need your current location. "
                "The browser will request location permission."
            ),
            "requires_geolocation": True,
        })
        # After resume, user_location will be populated with the resume payload.
        logger.info(
            "graph.node_resume",
            node="maps_agent",
            session_id=session_id,
            location_received=user_location is not None,
        )

    if needs_location and (
        not isinstance(user_location, dict)
        or not isinstance(user_location.get("lat"), (int, float))
        or not isinstance(user_location.get("lng"), (int, float))
    ):
        response_text = (
            "Mình chưa có vị trí hiện tại nên chưa thể xếp hạng các quán gần bạn. "
            "Bạn có thể bật quyền vị trí, hoặc hỏi cụ thể theo khu vực như 'quán hải sản ở Hàm Ninh'."
            if language == "vi"
            else "I do not have your current location, so I cannot rank nearby places yet. "
            "You can enable location access or ask for a specific area such as seafood restaurants in Ham Ninh."
        )
        return {
            "places": [],
            "response_text": response_text,
            "suggestions": (
                ["Quán hải sản ở Hàm Ninh", "Tìm gần chợ Hàm Ninh", "Bật vị trí rồi thử lại"]
                if language == "vi"
                else ["Seafood in Ham Ninh", "Find near Ham Ninh market", "Enable location and retry"]
            ),
            "intent": state.get("intent") or "restaurant_search",
        }

    # Get PlaceRecommendationService from dependency injection
    services = get_services()
    places_service = services.places_service

    if places_service is None:
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.warning(
            "graph.node_exit",
            node="maps_agent",
            session_id=session_id,
            mode="no_places_service",
            duration_ms=elapsed,
        )
        error_message = (
            "Xin lỗi, dịch vụ gợi ý địa điểm hiện không khả dụng. "
            "Vui lòng thử lại sau."
            if language == "vi"
            else "Sorry, the place recommendation service is currently unavailable. "
            "Please try again later."
        )
        return {
            "places": [],
            "response_text": error_message,
        }

    # Call PlaceRecommendationService
    try:
        chat_response = await places_service.recommend(
            query=message,
            user_location=user_location,
            language=language,
            session_id=session_id,
            budget=budget_filter,
            accessibility=accessibility_required,
        )

        # Convert PlaceResult Pydantic models to dicts for AgentState
        places_dicts = [place.model_dump() for place in chat_response.places]

        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="maps_agent",
            session_id=session_id,
            mode="place_recommendation",
            place_count=len(places_dicts),
            duration_ms=elapsed,
        )

        return {
            "places": places_dicts,
            "response_text": chat_response.message,
            "intent": chat_response.intent or state.get("intent") or "restaurant_search",
            "run_status": "gathering",
            "current_step": "places",
            "tool_receipts": [{
                "tool": "place_recommendation",
                "status": "success",
                "result_count": len(places_dicts),
            }],
            "last_places": places_dicts,
            "last_place_query": message,
            "last_place_included_type": (
                "cafe"
                if any(term in message.lower() for term in ("cà phê", "cafe", "coffee", "quán cf"))
                else None
            ),
            "last_place_accessibility_required": accessibility_required,
            "last_place_user_location": user_location,
        }

    except Exception as exc:
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.error(
            "graph.node_exit",
            node="maps_agent",
            session_id=session_id,
            mode="service_error",
            error_type=type(exc).__name__,
            error=str(exc),
            duration_ms=elapsed,
        )
        error_message = (
            "Xin lỗi, đã xảy ra lỗi khi tìm kiếm địa điểm. "
            "Vui lòng thử lại sau."
            if language == "vi"
            else "Sorry, an error occurred while searching for places. "
            "Please try again later."
        )
        return {
            "places": [],
            "response_text": error_message,
        }
