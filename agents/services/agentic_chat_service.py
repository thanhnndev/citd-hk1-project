"""LLM-first soft-strict chat service for Ham Ninh assistant.

The LLM decides whether to answer directly or call a tool. Tools are
capabilities, not routes. This follows the LangGraph/ReAct pattern from docs:
the model receives conversation state plus tools, emits tool_calls only when
needed, and otherwise returns a normal assistant message.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncGenerator
from typing import Any, Literal

import structlog

from app.models.rag import RAGChunk
from app.models.response import ChatResponse, Citation
from agents.tools.retriever import Retriever

logger = structlog.get_logger(__name__)

ChatStatus = Literal[
    "understanding",
    "using_history",
    "searching_knowledge",
    "checking_places",
    "composing",
]

_SYSTEM_PROMPT = """\
Bạn là Trợ lý Hàm Ninh, một AI assistant cho du lịch bền vững tại làng chài Hàm Ninh.

Soft-strict rules:
1. You decide whether to answer directly, ask clarification, or call a tool.
2. Do NOT call tools for greetings, thanks, capability questions, usage questions, or short follow-ups that can be answered from conversation history.
3. Use conversation history to resolve follow-ups like "4 nhóm gì?", "ý là sao?", "nhóm đầu tiên?".
4. Call search_knowledge only for factual local knowledge that needs evidence.
5. Call search_places only for places, route/direction, maps, restaurants, stays, or travel logistics.
6. If a route/direction request lacks origin or destination, ask one focused clarification instead of searching random documents.
7. Never concatenate raw chunks. Summarize naturally and cite only relevant tool results.
8. If tool results are weak or unrelated, say what is missing and ask a follow-up.
9. Reply in the user's language.
"""

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search Ham Ninh knowledge for factual answers requiring citations: culture, history, food, experiences, travel notes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Concise factual search query."}
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_places",
            "description": "Find places or route/direction help for restaurants, hotels, attractions, maps, getting to/from Ham Ninh.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Place, route, or direction request."}
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]

_CAPABILITY_TEXT = {
    "vi": (
        "Mình có thể giúp theo 4 nhóm chính:\n"
        "1. Tìm địa điểm: quán hải sản, cà phê, chỗ lưu trú, điểm tham quan quanh Hàm Ninh.\n"
        "2. Hỏi đường và lịch trình: gợi ý cách đi, hỏi thêm điểm xuất phát/đích nếu chưa đủ thông tin.\n"
        "3. Văn hóa và lịch sử: tóm tắt nghề biển, đời sống làng chài, món ăn và trải nghiệm địa phương kèm nguồn khi cần.\n"
        "4. Giải thích gợi ý: cho biết vì sao một địa điểm được xếp hạng, gồm yếu tố địa phương, khoảng cách, chất lượng và khả năng tiếp cận."
    ),
    "en": (
        "I can help in 4 main ways:\n"
        "1. Find places: seafood spots, cafes, stays, and attractions around Ham Ninh.\n"
        "2. Directions and trip planning: suggest routes and ask for origin/destination when needed.\n"
        "3. Culture and history: summarize fishing life, local food, and experiences with sources when needed.\n"
        "4. Explain recommendations: show why a place ranks well, including local, distance, quality, and accessibility factors."
    ),
}

_GREETING_TEXT = {
    "vi": "Chào bạn! Mình là trợ lý AI về Hàm Ninh. Bạn có thể hỏi về địa điểm, đường đi, văn hóa/lịch sử hoặc gợi ý lịch trình.",
    "en": "Hello! I'm the Ham Ninh AI assistant. You can ask about places, directions, culture/history, or simple trip planning.",
}

_AI_DISCLOSURE = {
    "vi": "Mình là AI nên có thể sai; với đường đi, giờ mở cửa hoặc an toàn, bạn nên kiểm tra lại trên bản đồ/nguồn chính thức.",
    "en": "I'm an AI and can be wrong; for routes, opening hours, or safety, verify with a map or official source.",
}

class AgenticChatService:
    def __init__(self, *, retriever: Retriever | None, hybrid_retriever: Any | None, llm_service: Any, place_recommendation_service: Any | None = None) -> None:
        self._retriever = retriever
        self._hybrid_retriever = hybrid_retriever
        self._client = getattr(llm_service, "_client", None)
        self.model = getattr(llm_service, "model", "gpt-4o-mini")
        self._place_recommendation_service = place_recommendation_service
        self._last_citations: list[Citation] = []
        self._last_places: list[Any] = []
        self._last_reasoning_log: str | None = None
        self._last_intent: str | None = None

    async def answer(self, *, session_id: str, message: str, language: str = "vi", history: list[dict[str, str]] | None = None) -> ChatResponse:
        started = time.perf_counter()
        text = ""
        async for event in self.answer_stream(session_id=session_id, message=message, language=language, history=history):
            if event.startswith("["):
                continue
            text += event
        return ChatResponse(
            session_id=session_id,
            message=text,
            citations=self._last_citations,
            places=self._last_places,
            reasoning_log=self._last_reasoning_log,
            intent=self._last_intent,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
            fallback=False,
        )

    async def answer_stream(self, *, session_id: str, message: str, language: str = "vi", history: list[dict[str, str]] | None = None) -> AsyncGenerator[str, None]:
        lang = "en" if language == "en" else "vi"
        history = history or []
        self._last_citations = []
        self._last_places = []
        self._last_reasoning_log = None
        self._last_intent = None

        yield _status("understanding")

        safe_direct = _safe_direct_answer(message, history, lang)
        if safe_direct is not None:
            yield _status("using_history")
            yield safe_direct
            yield "[CITATIONS] []"
            yield "[DONE]"
            self._last_intent = "conversational"
            return

        if self._client is None:
            clarification = _clarification_answer(message, lang)
            yield clarification
            yield "[CITATIONS] []"
            yield "[DONE]"
            self._last_intent = "clarification"
            return

        messages = self._build_messages(message=message, language=lang, history=history)
        first = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=_TOOLS,
            tool_choice="auto",
            temperature=0.1,
            max_tokens=350,
        )
        assistant = first.choices[0].message
        tool_calls = assistant.tool_calls or []

        if not tool_calls:
            content = assistant.content or _clarification_answer(message, lang)
            yield content
            yield "[CITATIONS] []"
            yield "[DONE]"
            self._last_intent = "conversational"
            return

        messages.append(assistant.model_dump(exclude_none=True))
        citations: list[Citation] = []

        for call in tool_calls[:2]:
            name = call.function.name
            args = _json_args(call.function.arguments)
            query = str(args.get("query") or message)
            if name == "search_knowledge":
                yield _status("searching_knowledge")
                chunks, tool_citations = await self._search_knowledge(query)
                citations.extend(tool_citations)
                content = _knowledge_tool_content(chunks)
                self._last_intent = "cultural_query"
            elif name == "search_places" and self._place_recommendation_service is not None:
                yield _status("checking_places")
                place_response = await self._place_recommendation_service.recommend(query=query, language=lang, session_id=session_id)
                self._last_places = place_response.places
                self._last_reasoning_log = place_response.reasoning_log
                self._last_intent = place_response.intent
                content = _places_tool_content(place_response)
            else:
                content = "Tool unavailable. Ask one concise clarification instead of inventing."
            messages.append({"role": "tool", "tool_call_id": call.id, "content": content})

        yield _status("composing")
        final_stream = await self._client.chat.completions.create(
            model=self.model,
            messages=messages + [{"role": "system", "content": "Answer naturally. Use only relevant tool facts. Do not list raw chunks. Ask clarification if tool output is insufficient."}],
            temperature=0.2,
            max_tokens=520,
            stream=True,
        )
        async for chunk in final_stream:
            token = chunk.choices[0].delta.content
            if token:
                yield token

        self._last_citations = citations[:5]
        yield f"[CITATIONS] {json.dumps([c.model_dump() for c in self._last_citations], ensure_ascii=False)}"
        yield "[DONE]"

    def _build_messages(self, *, message: str, language: str, history: list[dict[str, str]]) -> list[dict[str, Any]]:
        lang_name = "Vietnamese" if language == "vi" else "English"
        messages: list[dict[str, Any]] = [{"role": "system", "content": _SYSTEM_PROMPT + f"\nPreferred language: {lang_name}."}]
        for item in history[-8:]:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": message})
        return messages

    async def _search_knowledge(self, query: str) -> tuple[list[RAGChunk], list[Citation]]:
        if self._hybrid_retriever is not None:
            result, citations = await self._hybrid_retriever.search_with_citations(query, top_k=5)
            return result.chunks, citations
        if self._retriever is not None:
            result, citations = self._retriever.search_with_citations(query, top_k=5)
            return result.chunks, citations
        return [], []

def _status(value: ChatStatus) -> str:
    return f"[STATUS] {value}"

def _json_args(raw: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}

def _normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())

def _safe_direct_answer(message: str, history: list[dict[str, str]], language: str) -> str | None:
    normalized = _normalize(message)
    if not normalized:
        return None

    if _is_greeting(normalized):
        return _GREETING_TEXT[language]

    if _is_capability_question(normalized) or _asks_about_previous_groups(normalized, history):
        return _CAPABILITY_TEXT[language]

    if _is_ai_disclosure_question(normalized):
        return _AI_DISCLOSURE[language]

    if _looks_like_ambiguous_route(normalized):
        return _route_clarification(language)

    return None

def _is_greeting(normalized: str) -> bool:
    greetings = ("chào", "xin chào", "hello", "hi", "hey", "chào bạn", "hi bạn")
    return normalized in greetings

def _is_capability_question(normalized: str) -> bool:
    patterns = (
        r"bạn .*giúp.*gì",
        r"bạn .*làm.*gì",
        r"bạn .*hỗ trợ.*gì",
        r"giúp được gì",
        r"có thể giúp gì",
        r"what can you do",
        r"how can you help",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)

def _asks_about_previous_groups(normalized: str, history: list[dict[str, str]]) -> bool:
    if not re.search(r"\b(4|bốn|bon)\b.*(nhóm|nhom)|nhóm gì|nhom gi", normalized):
        return False
    recent_assistant = "\n".join(item.get("content", "") for item in history[-4:] if item.get("role") == "assistant").lower()
    return "4 nhóm" in recent_assistant or "4 main ways" in recent_assistant or "4 nhóm chính" in recent_assistant

def _is_ai_disclosure_question(normalized: str) -> bool:
    return "ai" in normalized and any(term in normalized for term in ("sai", "tin được", "reliable", "trust"))

def _looks_like_ambiguous_route(normalized: str) -> bool:
    route_terms = ("tìm đường", "đường đi", "chỉ đường", "cách đi", "route", "direction", "get there")
    has_route = any(term in normalized for term in route_terms)
    if not has_route:
        return False
    has_origin = any(term in normalized for term in ("từ ", "from "))
    has_destination = any(term in normalized for term in ("đến ", "to ", "hàm ninh", "ham ninh"))
    return not (has_origin and has_destination)

def _route_clarification(language: str) -> str:
    if language == "vi":
        return "Mình giúp được. Bạn cho mình điểm xuất phát và điểm muốn đến ở Hàm Ninh nhé? Ví dụ: 'Từ Dương Đông đến làng chài Hàm Ninh'."
    return "I can help. Tell me your starting point and destination in Ham Ninh, e.g. 'From Duong Dong to Ham Ninh fishing village'."

def _clarification_answer(message: str, language: str) -> str:
    if language == "vi":
        return "Mình chưa đủ thông tin để xử lý chính xác. Bạn nói rõ hơn điểm muốn hỏi hoặc mục tiêu chuyến đi được không?"
    return "I need a little more detail to answer accurately. Could you clarify what you want to do or where you want to go?"

def _knowledge_tool_content(chunks: list[RAGChunk]) -> str:
    if not chunks:
        return "No relevant knowledge results found."
    payload = []
    for i, chunk in enumerate(chunks[:5], 1):
        payload.append({"source": i, "title": chunk.title, "text": chunk.text[:900]})
    return json.dumps(payload, ensure_ascii=False)

def _places_tool_content(place_response: ChatResponse) -> str:
    payload = {
        "message": place_response.message,
        "reasoning_log": place_response.reasoning_log,
        "places": [place.model_dump() for place in place_response.places[:5]],
    }
    return json.dumps(payload, ensure_ascii=False)
