"""Deterministic routing and response helpers for AgentService."""

from __future__ import annotations

import json
from typing import Any, Literal

from app.models.rag import RAGChunk
from agents.graph.state import AgentState, SYSTEM_PROMPT
from agents.services.place_recommendation_service import PLACE_RECOMMENDATION_INTENT

def _norm(text: str) -> str:
    return " ".join((text or "").strip().lower().split())

def _fallback_action(message: str, history: list[dict[str, str]]) -> Literal["direct", "places", "knowledge", "clarify"]:
    text = _norm(message)
    if not text:
        return "clarify"
    if _is_greeting(text) or _is_capability(text) or _is_followup(text, history) or _is_place_capability(text):
        return "direct"
    if _is_ambiguous_route(text):
        return "clarify"
    if any(term in text for term in ("văn hóa", "lịch sử", "culture", "history", "truyền thống", "dân chài")):
        return "knowledge"
    if _is_place_or_route(text):
        return "places"
    if len(text) < 8:
        return "clarify"
    return "knowledge"

def _is_greeting(text: str) -> bool:
    return text in {"chào", "chào bạn", "xin chào", "hello", "hi", "hey", "cảm ơn", "thanks", "ok", "oke"}

def _is_capability(text: str) -> bool:
    return any(term in text for term in ("giúp được gì", "giúp gì", "làm được gì", "hỗ trợ gì", "what can you do", "how can you help"))

def _is_followup(text: str, history: list[dict[str, str]]) -> bool:
    if not any(item.get("role") == "assistant" for item in history[-4:]):
        return False
    return (
        text in {"?", "??", "là sao", "ý là sao", "gì", "4 nhóm gì", "4 nhom gi"}
        or any(term in text for term in ("ví dụ", "cụ thể", "example"))
        or (any(term in text for term in ("tươi ngon", "đồ ngon", "món ngon")) and len(text.split()) <= 6)
    )

def _is_place_capability(text: str) -> bool:
    has_place = any(term in text for term in ("khách sạn", "hotel", "lưu trú", "chỗ ở", "nhà hàng", "restaurant", "homestay"))
    asks_capability = any(term in text for term in ("được không", "có được", "có thể", "can you"))
    return has_place and asks_capability

def _is_ambiguous_route(text: str) -> bool:
    route_terms = ("tìm đường", "đường đi", "cách đi", "route", "direction")
    has_route = any(term in text for term in route_terms)
    has_destination = any(term in text for term in ("đến ", "tới ", "toi ", "to ", "hàm ninh", "ham ninh", "chợ", "cho "))
    return has_route and not has_destination

def _is_place_or_route(text: str) -> bool:
    place_terms = (
        "nhà hàng", "quán", "đồ ngon", "món ngon", "ăn", "hải sản", "cafe", "cà phê", "khách sạn",
        "homestay", "lưu trú", "chỗ ở", "hotel", "restaurant", "seafood", "stay", "place", "nearby",
        "cf", "coffee", "view"
    )
    action_terms = (
        "kiếm", "tìm", "gợi ý", "đề xuất", "recommend", "find", "search", "gần đây", "quanh đây",
        "ở đâu", "có", "nào", "gì", "giá", "sao"
    )
    route_terms = ("chỉ đường", "đường đi", "cách đi", "đi đến", "đi tới", "route", "direction", "map")
    
    has_place = any(term in text for term in place_terms)
    has_action = any(term in text for term in action_terms)
    is_descriptive = has_place and len(text.split()) >= 3
    
    return any(term in text for term in route_terms) or (has_place and has_action) or is_descriptive

def _direct_answer(message: str, history: list[dict[str, str]], language: str) -> str:
    text = _norm(message)
    if _is_greeting(text):
        return "Chào bạn! Mình là trợ lý AI về Hàm Ninh. Bạn có thể hỏi về địa điểm, đường đi, văn hóa/lịch sử hoặc gợi ý lịch trình." if language == "vi" else "Hello! I'm the Ham Ninh AI assistant. You can ask about places, directions, culture/history, or trip planning."
    if _is_place_capability(text):
        return "Được. Bạn cho mình biết loại địa điểm, ngân sách/khu vực gần đâu và yêu cầu đi kèm nhé." if language == "vi" else "Yes. Tell me the place type, budget/area, and any requirements."
    if any(term in text for term in ("ví dụ", "cụ thể", "example")):
        return _capability_examples(language)
    if any(term in text for term in ("tươi ngon", "đồ ngon", "món ngon")):
        return _fresh_food_answer(language)
    return _capability_answer(language)

def _capability_answer(language: str) -> str:
    if language == "vi":
        return (
            "Mình có thể giúp theo 4 nhóm chính:\n"
            "1. Tìm địa điểm: quán hải sản, cà phê, chỗ lưu trú, điểm tham quan quanh Hàm Ninh.\n"
            "2. Hỏi đường và lịch trình: gợi ý cách đi, hỏi thêm điểm xuất phát/đích nếu chưa đủ thông tin.\n"
            "3. Văn hóa và lịch sử: tóm tắt nghề biển, đời sống làng chài, món ăn và trải nghiệm địa phương kèm nguồn khi cần.\n"
            "4. Giải thích gợi ý: cho biết vì sao một địa điểm được xếp hạng."
        )
    return "I can help with places, directions, Ham Ninh culture/history, and explaining recommendations."

def _capability_examples(language: str) -> str:
    if language == "vi":
        return (
            "Ví dụ cụ thể bạn có thể hỏi:\n"
            "1. 'Kiếm nhà hàng hải sản gần đây.'\n"
            "2. 'Có khách sạn/homestay nào quanh Hàm Ninh không?'\n"
            "3. 'Từ Dương Đông đi Hàm Ninh thế nào?'\n"
            "4. 'Làng chài Hàm Ninh có gì đặc biệt?'\n"
            "5. 'Vì sao quán này được xếp cao?'"
        )
    return "Examples: find nearby seafood, find stays, ask directions, ask village history, or ask why a place ranks high."

def _fresh_food_answer(language: str) -> str:
    if language == "vi":
        return "Có. Hàm Ninh hợp nhất với hải sản tươi như ghẹ, tôm, mực, cá biển và các quán/nhà bè gần làng chài. Nếu muốn địa điểm cụ thể, hãy hỏi 'kiếm nhà hàng gần đây'."
    return "Yes. Ham Ninh is best for fresh seafood such as crab, shrimp, squid, fish, and seafood rafts/restaurants near the fishing village."

def _knowledge_fallback_answer(state: AgentState) -> str:
    citations = state.get("citations", [])
    if not citations:
        return "Mình chưa có nguồn đủ chắc để trả lời câu này." if state["language"] == "vi" else "I do not have enough reliable source context to answer that."
    return "Mình tìm được nguồn liên quan. Bạn mở phần Nguồn tham khảo để kiểm tra chi tiết." if state["language"] == "vi" else "I found relevant sources. Open Sources to inspect the details."

def _clarify_message(language: str) -> str:
    return "Bạn nói rõ hơn mục tiêu hoặc thông tin cần tìm được không?" if language == "vi" else "Could you clarify what you want to find or know?"

def _place_unavailable_message(language: str) -> str:
    return "Tính năng tìm địa điểm đang không khả dụng, nên mình không dùng nguồn RAG để giả kết quả địa điểm." if language == "vi" else "Place search is unavailable, so I will not fake place results from documents."

def _too_many_tools_message(language: str) -> str:
    return "Mình chưa chốt được công cụ phù hợp. Bạn nói rõ hơn yêu cầu nhé." if language == "vi" else "I could not settle on the right tool. Please clarify your request."

def _extract_suggestions(text: str) -> tuple[str, list[str]]:
    if not text:
        return "", []
    if "[SUGGESTIONS]" in text:
        parts = text.split("[SUGGESTIONS]")
        main_message = parts[0].strip()
        suggestions_str = parts[1].strip()
        # Parse suggestions_str which is separated by "|"
        suggestions = [s.strip() for s in suggestions_str.split("|") if s.strip()]
        return main_message, suggestions
    return text, []

def _get_default_suggestions(intent: str | None, language: str, has_places: bool = False, has_citations: bool = False, fallback: bool = False) -> list[str]:
    if language == "vi":
        if has_places:
            return ["Hiển thị trên bản đồ", "Kể thêm về chỗ này", "Có tiếp cận được không?"]
        if has_citations:
            return ["Tóm tắt nguồn tham khảo", "Hỏi thêm về chủ đề này"]
        if fallback:
            return ["Thử hỏi theo hướng khác", "Hỏi về làng chài"]
        return ["Bạn còn làm được gì?", "Kể về ẩm thực địa phương"]
    else:
        if has_places:
            return ["Show on map", "Tell me more", "Is it accessible?"]
        if has_citations:
            return ["Summarize the sources", "Follow up on this"]
        if fallback:
            return ["Try a different angle", "Ask about the village"]
        return ["What else can you do?", "Tell me about local food"]


def _messages_for_llm(*, message: str, history: list[dict[str, str]], language: str) -> list[dict[str, Any]]:
    lang_name = "English" if language == "en" else "Vietnamese"
    messages: list[dict[str, Any]] = [{"role": "system", "content": f"{SYSTEM_PROMPT}\nPreferred language: {lang_name}."}]
    for item in history[-8:]:
        if item.get("role") in {"user", "assistant"} and item.get("content"):
            messages.append({"role": item["role"], "content": item["content"]})
    messages.append({"role": "user", "content": message})
    return messages

def _json_args(raw: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}

def _chunk_payload(chunk: RAGChunk, index: int) -> dict[str, str | int]:
    return {"source": index, "title": chunk.title, "text": chunk.text[:900]}

def _status_for_state(state: AgentState) -> str:
    if state.get("places"):
        return "[STATUS] checking_places"
    if state.get("citations"):
        return "[STATUS] searching_knowledge"
    return "[STATUS] using_history"

def _status_for_tool_calls(tool_calls: list[Any]) -> str:
    names = {call.function.name for call in tool_calls}
    if "search_places" in names:
        return "[STATUS] checking_places"
    if "search_knowledge" in names:
        return "[STATUS] searching_knowledge"
    return "[STATUS] composing"

