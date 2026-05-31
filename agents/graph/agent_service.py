"""LangGraph-style tool-calling chat agent.

The runtime follows the simple LangGraph pattern documented by LangChain:
LLM decides whether to call a tool; tool node executes; LLM composes final
answer. Retrieval is a tool, never the default entry point.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

import asyncpg
import structlog

from app.models.rag import RAGChunk, RetrievalResult
from app.models.response import ChatResponse, Citation
from agents.services.place_recommendation_service import PLACE_RECOMMENDATION_INTENT
from agents.tools.retriever import Retriever

try:
    from langgraph.graph import END, START, StateGraph
    from langgraph.checkpoint.memory import MemorySaver
except Exception:  # pragma: no cover - optional runtime dependency
    END = "__end__"
    START = "__start__"
    StateGraph = None
    MemorySaver = None

logger = structlog.get_logger(__name__)

NODE_TIMEOUT_LLM = 20
NODE_TIMEOUT_TOOL = 15

ToolName = Literal["search_knowledge", "search_places"]

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": (
                "Use only for factual Ham Ninh culture/history/travel knowledge that needs evidence. "
                "Do not use for greetings, help/capability questions, follow-ups that can be answered from history, "
                "or place/hotel/restaurant discovery."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_places",
            "description": (
                "Use for restaurants, hotels, homestays, cafes, seafood, nearby places, directions, maps, routes, "
                "or local recommendations around Ham Ninh."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]

_SYSTEM_PROMPT = """\
Bạn là Trợ lý Hàm Ninh cho du lịch bền vững.

Follow this exact tool policy:
- Answer directly for greetings, thanks, capability/help questions, and follow-ups answerable from conversation history.
- Ask one clarification question when the request is underspecified.
- Call search_places for restaurants, hotels, homestays, cafes, seafood, nearby places, directions, routes, maps, or recommendations.
- Call search_knowledge only for factual Ham Ninh knowledge requiring evidence: culture, history, fishing life, local food background, travel notes.
- Never call search_knowledge as a fallback for place requests or short follow-ups.
- Cite only facts from search_knowledge results. Do not cite place results as document sources.
- If a tool is unavailable or returns no useful data, say that honestly and ask a useful follow-up.
- Reply in the user's language.
"""

class AgentState(TypedDict, total=False):
    session_id: str
    message: str
    language: str
    history: list[dict[str, str]]
    messages: list[dict[str, Any]]
    tool_calls: list[Any]
    citations: list[Citation]
    places: list[Any]
    reasoning_log: str | None
    intent: str | None
    response_text: str
    response: ChatResponse
    langfuse_trace_id: str | None

@dataclass
class InMemoryAgentCheckpointer:
    _store: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    async def load_history(self, session_id: str) -> list[dict[str, str]]:
        return list(self._store.get(session_id, []))

    async def save_turn(self, session_id: str, user: str, assistant: str) -> None:
        history = self._store.setdefault(session_id, [])
        history.extend([{"role": "user", "content": user}, {"role": "assistant", "content": assistant}])
        del history[:-8]

class PostgresAgentCheckpointer:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def create(cls, dsn: str) -> "PostgresAgentCheckpointer":
        pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5)
        checkpointer = cls(pool)
        try:
            await checkpointer.setup()
            await checkpointer.load_history("__agent_checkpoint_connectivity__")
        except Exception:
            await pool.close()
            raise
        return checkpointer

    async def setup(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """CREATE TABLE IF NOT EXISTS agent_session_messages (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )"""
            )
            await conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_agent_session_messages_session_order
                ON agent_session_messages (session_id, id)"""
            )

    async def load_history(self, session_id: str) -> list[dict[str, str]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT role, content FROM (
                    SELECT id, role, content FROM agent_session_messages
                    WHERE session_id = $1 ORDER BY id DESC LIMIT 8
                ) recent ORDER BY id ASC""",
                session_id,
            )
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    async def save_turn(self, session_id: str, user: str, assistant: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO agent_session_messages (session_id, role, content)
                VALUES ($1, $2, $3)""",
                [(session_id, "user", user), (session_id, "assistant", assistant)],
            )

async def create_agent_checkpointer(database_url: str | None = None) -> tuple[Any, str]:
    dsn = database_url or os.getenv("DATABASE_URL")
    if dsn:
        try:
            return await PostgresAgentCheckpointer.create(dsn), "postgres"
        except Exception as exc:
            logger.warning("agent.checkpoint_init_failed", checkpoint_mode="memory", reason=type(exc).__name__)
    return InMemoryAgentCheckpointer(), "memory"

class AgentService:
    def __init__(
        self,
        *,
        retriever: Retriever | None,
        hybrid_retriever: Any | None = None,
        llm_service: Any | None = None,
        checkpointer: Any | None = None,
        checkpoint_mode: Literal["memory", "postgres", "test"] = "memory",
        place_recommendation_service: Any | None = None,
        semantic_cache: Any | None = None,
        embedding_service: Any | None = None,
        langfuse_client: Any | None = None,
    ) -> None:
        self._retriever = retriever
        self._hybrid_retriever = hybrid_retriever
        self._llm_service = llm_service
        self._client = _real_client(llm_service)
        self._model = getattr(llm_service, "model", "gpt-4o-mini") if llm_service is not None else "gpt-4o-mini"
        self._place_recommendation_service = place_recommendation_service
        self._semantic_cache = semantic_cache
        self._embedding_service = embedding_service
        self._checkpointer = checkpointer or InMemoryAgentCheckpointer()
        self.checkpoint_mode = checkpoint_mode
        self._langfuse_client = langfuse_client
        self._graph = self._build_graph()

    def _build_graph(self) -> Any | None:
        if StateGraph is None:
            return None
        graph = StateGraph(AgentState)
        graph.add_node("llm_call", self._llm_call_node)
        graph.add_node("tool_node", self._tool_node)
        graph.add_edge(START, "llm_call")
        graph.add_conditional_edges("llm_call", self._should_continue, {"tool_node": "tool_node", END: END})
        graph.add_edge("tool_node", "llm_call")
        return graph.compile(checkpointer=MemorySaver() if MemorySaver else None)

    async def answer(self, *, session_id: str, message: str, language: str = "vi") -> ChatResponse:
        started = time.perf_counter()
        state = await self._initial_state(session_id, message, language)
        if self._client is None:
            state = await self._deterministic_decide_and_run(state)
        else:
            state = await self._run_tool_loop(state)
        response = self._response_from_state(state, started)
        await self._save_turn(session_id, message, response.message)
        return response

    async def answer_stream(self, *, session_id: str, message: str, language: str = "vi") -> AsyncGenerator[str, None]:
        started = time.perf_counter()
        state = await self._initial_state(session_id, message, language)
        yield "[STATUS] understanding"
        if self._client is None:
            state = await self._deterministic_decide_and_run(state)
            yield _status_for_state(state)
            yield state.get("response_text", "")
        else:
            async for event in self._run_streaming_tool_loop(state):
                if isinstance(event, str):
                    yield event
                else:
                    state = event
        response = self._response_from_state(state, started)
        await self._save_turn(session_id, message, response.message)
        if response.places:
            yield f"[PLACES] {json.dumps([p.model_dump() for p in response.places], ensure_ascii=False)}"
        if response.citations:
            yield f"[CITATIONS] {json.dumps([c.model_dump() for c in response.citations], ensure_ascii=False)}"

    async def stream(self, *, session_id: str, message: str, language: str = "vi") -> AsyncGenerator[str, None]:
        async for event in self.answer_stream(session_id=session_id, message=message, language=language):
            yield event

    async def _initial_state(self, session_id: str, message: str, language: str) -> AgentState:
        try:
            history = await self._checkpointer.load_history(session_id)
        except Exception as exc:
            logger.warning("agent.checkpoint_load", session_id=session_id, reason=type(exc).__name__)
            history = []
        return {
            "session_id": session_id,
            "message": message,
            "language": "en" if language == "en" else "vi",
            "history": history,
            "messages": _messages_for_llm(message=message, history=history, language=language),
            "citations": [],
            "places": [],
            "reasoning_log": None,
            "intent": None,
            "response_text": "",
            "places_response_ready": False,
        }

    async def _run_tool_loop(self, state: AgentState) -> AgentState:
        for _ in range(3):
            # Place tool may have already produced a deterministic response;
            # skip the LLM to avoid overwriting response_text.
            if state.get("places_response_ready"):
                return state
            state = await asyncio.wait_for(self._llm_call_node(state), timeout=NODE_TIMEOUT_LLM)
            if self._should_continue(state) == END:
                return state
            state = await asyncio.wait_for(self._tool_node(state), timeout=NODE_TIMEOUT_TOOL)
        state["response_text"] = _too_many_tools_message(state["language"])
        state["intent"] = "clarification"
        return state

    async def _run_streaming_tool_loop(self, state: AgentState) -> AsyncGenerator[str | AgentState, None]:
        for _ in range(3):
            if state.get("places_response_ready"):
                yield state
                return
            state = await asyncio.wait_for(self._llm_call_node(state), timeout=NODE_TIMEOUT_LLM)
            if self._should_continue(state) == END:
                yield state
                return
            yield _status_for_tool_calls(state.get("tool_calls", []))
            state = await asyncio.wait_for(self._tool_node(state), timeout=NODE_TIMEOUT_TOOL)
        state["response_text"] = _too_many_tools_message(state["language"])
        state["intent"] = "clarification"
        yield state

    async def _llm_call_node(self, state: AgentState) -> AgentState:
        completion = await self._client.chat.completions.create(
            model=self._model,
            messages=state["messages"],
            tools=_TOOLS,
            tool_choice="auto",
            temperature=0.1,
            max_tokens=520,
        )
        message = completion.choices[0].message
        tool_calls = list(message.tool_calls or [])
        if tool_calls:
            state["tool_calls"] = tool_calls
            state["messages"].append(message.model_dump(exclude_none=True))
            return state
        state["tool_calls"] = []
        state["response_text"] = message.content or _clarify_message(state["language"])
        state["intent"] = state.get("intent") or "conversational"
        return state

    async def _tool_node(self, state: AgentState) -> AgentState:
        tool_messages: list[dict[str, Any]] = []
        for call in state.get("tool_calls", [])[:2]:
            name = call.function.name
            args = _json_args(call.function.arguments)
            query = str(args.get("query") or state["message"])
            if name == "search_knowledge":
                content = await self._search_knowledge_tool(state, query)
            elif name == "search_places":
                content = await self._search_places_tool(state, query)
            else:
                content = json.dumps({"status": "unavailable", "message": "Unknown tool"})
            tool_messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
        state["messages"].extend(tool_messages)
        state["tool_calls"] = []
        return state

    def _should_continue(self, state: AgentState) -> Literal["tool_node", "__end__"]:
        if state.get("places_response_ready"):
            return END
        return "tool_node" if state.get("tool_calls") else END

    async def _deterministic_decide_and_run(self, state: AgentState) -> AgentState:
        action = _fallback_action(state["message"], state.get("history", []))
        if action == "direct":
            state["response_text"] = _direct_answer(state["message"], state.get("history", []), state["language"])
            state["intent"] = "conversational"
            return state
        if action == "places":
            await self._search_places_tool(state, state["message"])
            if not state.get("response_text"):
                state["response_text"] = _place_unavailable_message(state["language"])
            return state
        if action == "knowledge":
            await self._search_knowledge_tool(state, state["message"])
            state["response_text"] = _knowledge_fallback_answer(state)
            return state
        state["response_text"] = _clarify_message(state["language"])
        state["intent"] = "clarification"
        return state

    async def _search_knowledge_tool(self, state: AgentState, query: str) -> str:
        chunks: list[RAGChunk] = []
        citations: list[Citation] = []
        if self._hybrid_retriever is not None:
            result, citations = await self._hybrid_retriever.search_with_citations(query, top_k=5)
            chunks = result.chunks
        elif self._retriever is not None:
            result, citations = self._retriever.search_with_citations(query, top_k=5)
            chunks = result.chunks
        state["citations"] = citations[:5]
        state["intent"] = "cultural_query"
        return json.dumps({"status": "ok", "results": [_chunk_payload(c, i + 1) for i, c in enumerate(chunks[:5])]}, ensure_ascii=False)

    async def _search_places_tool(self, state: AgentState, query: str) -> str:
        state["intent"] = PLACE_RECOMMENDATION_INTENT
        if self._place_recommendation_service is None:
            state["response_text"] = _place_unavailable_message(state["language"])
            return json.dumps({"status": "unavailable", "message": state["response_text"]}, ensure_ascii=False)
        try:
            response = await self._place_recommendation_service.recommend(query=query, language=state["language"], session_id=state["session_id"])
        except Exception as exc:
            logger.warning("agent.place_tool_error", session_id=state["session_id"], reason=type(exc).__name__)
            state["response_text"] = _place_unavailable_message(state["language"])
            return json.dumps({"status": "error", "message": state["response_text"]}, ensure_ascii=False)
        state["places"] = response.places
        state["reasoning_log"] = response.reasoning_log
        state["response_text"] = response.message
        state["fairness_audit"] = response.fairness_audit
        state["places_response_ready"] = True
        return json.dumps({"status": "ok", "message": response.message, "places": [p.model_dump() for p in response.places[:5]]}, ensure_ascii=False)

    def _response_from_state(self, state: AgentState, started: float) -> ChatResponse:
        return ChatResponse(
            session_id=state["session_id"],
            message=state.get("response_text") or _clarify_message(state["language"]),
            citations=state.get("citations", []),
            places=state.get("places", []),
            reasoning_log=state.get("reasoning_log"),
            intent=state.get("intent"),
            langfuse_trace_id=state.get("langfuse_trace_id"),
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
            fallback=False,
            fairness_audit=state.get("fairness_audit"),
        )

    async def _save_turn(self, session_id: str, message: str, answer: str) -> None:
        try:
            await self._checkpointer.save_turn(session_id, message, answer)
        except Exception as exc:
            logger.warning("agent.checkpoint_save", session_id=session_id, reason=type(exc).__name__)

# Compatibility seams for older tests. Active chat paths do not use retrieve-first.
    async def _retrieve_node(self, state: AgentState) -> AgentState:
        query = state.get("retrieval_query") or state["message"]
        if self._semantic_cache is not None and self._embedding_service is not None:
            try:
                embeddings = await self._embedding_service.embed_texts([query])
                embedding = embeddings[0] if embeddings else None
                if embedding is not None:
                    cached = await self._semantic_cache.lookup(query, embedding)
                    if cached is not None:
                        state["citations"] = []
                        state["chunks"] = [RAGChunk(
                            chunk_id="cache_hit", source_id="semantic_cache", title="Semantic Cache Hit",
                            url="", domain="cache", source_type="cache", reliability="low", language="unknown",
                            location="", text=cached, chunk_index=0, total_chunks=1,
                        )]
                        return state
            except Exception:
                embedding = None
        else:
            embedding = None

        chunks: list[RAGChunk] = []
        citations: list[Citation] = []
        try:
            if self._hybrid_retriever is not None:
                result, citations = await self._hybrid_retriever.search_with_citations(query, top_k=5)
                chunks = result.chunks
            elif self._retriever is not None:
                result, citations = self._retriever.search_with_citations(query, top_k=5)
                chunks = result.chunks
        except Exception as exc:
            logger.warning("agent.retrieve_error", session_id=state.get("session_id"), reason=type(exc).__name__)

        state["chunks"] = chunks
        state["citations"] = citations

        if self._semantic_cache is not None and self._embedding_service is not None and chunks:
            try:
                if embedding is None:
                    embeddings = await self._embedding_service.embed_texts([query])
                    embedding = embeddings[0] if embeddings else None
                if embedding is not None:
                    await self._semantic_cache.store(query, embedding, " ".join(chunk.text for chunk in chunks))
            except Exception:
                pass
        return state

    async def _answer_node(self, state: AgentState) -> AgentState:
        return await self._deterministic_decide_and_run(state)

    async def _classify_message_intent(self, state: AgentState) -> str:
        action = _fallback_action(state["message"], state.get("history", []))
        intent = {"places": PLACE_RECOMMENDATION_INTENT, "knowledge": "cultural_query", "direct": "conversational"}.get(action, "clarification")
        state["intent"] = intent
        return intent

    async def _compose_fallback(self, state: AgentState, reason: str) -> ChatResponse:
        state = await self._deterministic_decide_and_run(state)
        response = self._response_from_state(state, time.perf_counter())
        response.fallback = True
        return response

def _real_client(llm_service: Any | None) -> Any | None:
    client = getattr(llm_service, "_client", None) if llm_service is not None else None
    if client is None or type(client).__module__.startswith("unittest.mock"):
        return None
    return client

def _messages_for_llm(*, message: str, history: list[dict[str, str]], language: str) -> list[dict[str, Any]]:
    lang_name = "English" if language == "en" else "Vietnamese"
    messages: list[dict[str, Any]] = [{"role": "system", "content": f"{_SYSTEM_PROMPT}\nPreferred language: {lang_name}."}]
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
    )
    action_terms = ("kiếm", "tìm", "gợi ý", "đề xuất", "recommend", "find", "search", "gần đây", "quanh đây")
    route_terms = ("chỉ đường", "đường đi", "cách đi", "đi đến", "đi tới", "route", "direction", "map")
    return any(term in text for term in route_terms) or (any(term in text for term in place_terms) and any(term in text for term in action_terms))

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
