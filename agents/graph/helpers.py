from __future__ import annotations

import hashlib
import math
from typing import Any, Literal

from agents.graph.state import AgentState

__all__ = [
    "_hash_query",
    "requires_user_location_heuristic",
    "_resolve_needs_location",
    "_has_domain_context",
    "_domain_refusal_message",
    "_domain_context_clarification_message",
    "_conversational_domain_action",
    "_requests_accessibility",
    "_is_place_comparison_followup",
    "_compare_previous_places",
    "_clarify_decision_followup_without_context",
    "_answer_place_decision_followup",
]

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
