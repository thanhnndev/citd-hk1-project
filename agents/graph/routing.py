"""Prompt and response helpers for the Ham Ninh graph.

Semantic intent routing belongs to the LangGraph LLM/tool loop. This module
keeps only deterministic conversational shortcuts and serialization helpers.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from app.models.rag import RAGChunk
from agents.graph.state import AgentState, SYSTEM_PROMPT

ConversationAction = Literal["direct", "clarify", "llm"]


def _norm(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _fallback_action(message: str, history: list[dict[str, str]] | None = None) -> ConversationAction:
    """Return only safe deterministic conversation actions.

    Per LangGraph's tool-calling pattern, domain decisions such as knowledge vs
    places must stay inside the LLM/tool loop. This fallback handles only empty
    input and common non-domain conversational turns.
    """
    text = _norm(message)
    if not text:
        return "clarify"
    if _is_greeting_or_thanks(text) or _is_capability_question(text) or _is_history_nudge(text, history or []):
        return "direct"
    return "llm"


def _is_greeting_or_thanks(text: str) -> bool:
    return text in {
        "chào", "chào bạn", "xin chào", "hello", "hi", "hey",
        "cảm ơn", "cám ơn", "thanks", "thank you", "ok", "oke",
    }


def _is_capability_question(text: str) -> bool:
    return any(term in text for term in (
        "giúp được gì", "giúp gì", "làm được gì", "hỗ trợ gì",
        "what can you do", "how can you help",
    ))


def _is_history_nudge(text: str, history: list[dict[str, str]]) -> bool:
    if not any(item.get("role") == "assistant" for item in history[-4:]):
        return False
    return text in {"?", "??", "là sao", "ý là sao", "4 nhóm gì", "4 nhom gi"} or any(
        term in text for term in ("ví dụ", "cụ thể", "example")
    )


def _direct_answer(message: str, history: list[dict[str, str]], language: str) -> str:
    text = _norm(message)
    if _is_greeting_or_thanks(text):
        if language == "vi":
            return "Chào bạn! Mình là trợ lý AI về Hàm Ninh. Bạn có thể hỏi về địa điểm, đường đi, văn hóa/lịch sử hoặc gợi ý lịch trình."
        return "Hello! I'm the Ham Ninh AI assistant. You can ask about places, directions, culture/history, or trip planning."
    if any(term in text for term in ("ví dụ", "cụ thể", "example")):
        return _capability_examples(language)
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


def _knowledge_fallback_answer(state: AgentState) -> str:
    citations = state.get("citations", [])
    if not citations:
        return "Mình chưa có nguồn đủ chắc để trả lời câu này." if state["language"] == "vi" else "I do not have enough reliable source context to answer that."
    return "Mình tìm được nguồn liên quan. Bạn mở phần Nguồn tham khảo để kiểm tra chi tiết." if state["language"] == "vi" else "I found relevant sources. Open Sources to inspect the details."


def _clarify_message(language: str) -> str:
    return "Bạn nói rõ hơn mục tiêu hoặc thông tin cần tìm được không?" if language == "vi" else "Could you clarify what you want to find or know?"


def _llm_unavailable_message(language: str) -> str:
    return "Mình cần mô hình LLM để hiểu yêu cầu này. Bạn thử lại khi dịch vụ AI sẵn sàng nhé." if language == "vi" else "I need the LLM service to understand this request. Please try again when AI service is available."


def _place_unavailable_message(language: str) -> str:
    return "Tính năng tìm địa điểm đang không khả dụng, nên mình không dùng nguồn RAG để giả kết quả địa điểm." if language == "vi" else "Place search is unavailable, so I will not fake place results from documents."


def _too_many_tools_message(language: str) -> str:
    return "Mình chưa chốt được công cụ phù hợp. Bạn nói rõ hơn yêu cầu nhé." if language == "vi" else "I could not settle on the right tool. Please clarify your request."


def _extract_suggestions(text: str) -> tuple[str, list[str]]:
    if not text:
        return "", []
    if "[SUGGESTIONS]" in text:
        parts = text.split("[SUGGESTIONS]", 1)
        main_message = parts[0].strip()
        suggestions_str = parts[1].strip()
        suggestions = [s.strip() for s in suggestions_str.split("|") if s.strip()]
        return main_message, suggestions[:3]
    return text, []


def _get_default_suggestions(intent: str | None, language: str, has_places: bool = False, has_citations: bool = False, fallback: bool = False) -> list[str]:
    if language == "vi":
        if has_places:
            return ["Chỉ đường tới nơi này", "So sánh các địa điểm", "Tìm chỗ gần đó"]
        if has_citations:
            return ["Hải sản nào nổi bật?", "Tìm quán hải sản gần đây", "Kể thêm về làng chài"]
        if fallback:
            return ["Kể về làng chài Hàm Ninh", "Tìm quán hải sản", "Hỏi đường đến chợ Hàm Ninh"]
        return ["Kể về ẩm thực địa phương", "Tìm quán hải sản gần đây", "Chỉ đường đến chợ Hàm Ninh"]
    if has_places:
        return ["Get directions", "Compare these places", "Find something nearby"]
    if has_citations:
        return ["What seafood stands out?", "Find nearby seafood", "Tell me more about the village"]
    if fallback:
        return ["Ask about the fishing village", "Find seafood places", "Ask directions to Ham Ninh market"]
    return ["Tell me about local food", "Find nearby seafood", "Get directions to Ham Ninh market"]


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
        return "[STATUS] gathering:places"
    if state.get("citations"):
        return "[STATUS] gathering:knowledge"
    return "[STATUS] planning"


def _status_for_tool_calls(tool_calls: list[Any]) -> str:
    names: set[str] = set()
    for call in tool_calls:
        function = getattr(call, "function", None)
        name = getattr(function, "name", None)
        if isinstance(call, dict):
            function_data = call.get("function") if isinstance(call.get("function"), dict) else {}
            name = function_data.get("name") or call.get("name")
        if name:
            names.add(str(name))
    if "search_places" in names:
        return "[STATUS] gathering:places"
    if "search_knowledge" in names:
        return "[STATUS] gathering:knowledge"
    return "[STATUS] executing"
