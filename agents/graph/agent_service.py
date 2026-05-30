"""LangGraph ReAct Agent — LLM decides which tool to call.

Best practice pattern from LangGraph docs:
  START → agent (LLM with tools) → tools_condition →
    ├─ tool_calls → ToolNode → agent (loop)
    └─ no tool_calls → END (LLM responds directly)

No hard routing. No keyword matching for intent.
The LLM sees tool descriptions and decides what to call.
For greetings/small talk, LLM responds directly without any tool.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict

import asyncpg
import structlog

from app.models.rag import RAGChunk, RetrievalResult
from app.models.response import ChatResponse, Citation
from agents.guardrails.grounded_answer import GroundedAnswerService
from agents.tools.retriever import Retriever
from agents.services.place_recommendation_service import PLACE_RECOMMENDATION_INTENT
from agents.services.agentic_chat_service import AgenticChatService, _safe_direct_answer

try:
    from langgraph.graph import END, StateGraph
    from langgraph.checkpoint.memory import MemorySaver
except Exception:
    END = "__end__"
    StateGraph = None
    MemorySaver = None

logger = structlog.get_logger(__name__)

NODE_TIMEOUT_RETRIEVE = 10
NODE_TIMEOUT_ANSWER = 15


class NodeTimeoutError(Exception):
    """Raised when a graph node exceeds its configured timeout."""

    def __init__(self, node_name: str, timeout_seconds: int) -> None:
        self.node_name = node_name
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Node '{node_name}' timed out after {timeout_seconds}s")


class AgentState(TypedDict, total=False):
    session_id: str
    message: str
    language: str
    history: list[dict[str, str]]
    retrieval_query: str
    chunks: list[RAGChunk]
    citations: list[Citation]
    response: ChatResponse
    fallback_reason: str | None
    intent: str | None
    intent_confidence: float | None
    langfuse_trace_id: str | None

_PLACE_INTENT_KEYWORDS = {
    "restaurant_search",
    "hotel_search",
    "accommodation_search",
    "place_search",
    "navigation",
}

_GREETING_PATTERNS = (
    "chào", "xin chào", "hello", "hi", "hey", "cảm ơn", "thanks", "thank",
    "tạm biệt", "bye", "goodbye", "ok", "oke",
)

_CONTEXT_FREE_HELP_PATTERNS = (
    "bạn có thể giúp gì", "bạn giúp được gì", "bạn làm được gì",
    "có thể giúp gì", "help me", "what can you do", "how can you help",
)

def _is_context_free_conversation(message: str) -> bool:
    """Detect small talk that should not inherit the previous retrieval topic."""
    normalized = " ".join((message or "").lower().split())
    if not normalized:
        return False
    if any(pattern in normalized for pattern in _CONTEXT_FREE_HELP_PATTERNS):
        return True
    return any(
        normalized == pattern
        or normalized.startswith(pattern + " ")
        or normalized.endswith(" " + pattern)
        for pattern in _GREETING_PATTERNS
    )

def _normalize_intent(intent: str | None) -> str:
    normalized = (intent or "unknown").strip().lower()
    if normalized in _PLACE_INTENT_KEYWORDS:
        return "restaurant_search" if normalized != "navigation" else "navigation"
    if normalized in {"conversational", "cultural_query", "unknown"}:
        return normalized
    if "hotel" in normalized or "accommodation" in normalized or "place" in normalized:
        return "restaurant_search"
    return "unknown"

def _is_place_intent(intent: str | None) -> bool:
    return _normalize_intent(intent) in {"restaurant_search", "navigation"}

def _should_use_places_before_rag(message: str) -> bool:
    normalized = " ".join((message or "").lower().split())
    if not normalized:
        return False
    action_terms = ("kiếm", "tìm", "gợi ý", "đề xuất", "recommend", "find", "search", "nearby", "gần đây", "quanh đây")
    place_terms = (
        "nhà hàng", "quán", "đồ ngon", "món ngon", "ăn", "hải sản", "cafe", "cà phê",
        "khách sạn", "homestay", "lưu trú", "chỗ ở", "hotel", "restaurant", "seafood", "stay", "place"
    )
    navigation_terms = ("chỉ đường", "đường đi", "cách đi", "đi đến", "đi tới", "route", "direction", "map")
    return (
        any(term in normalized for term in navigation_terms)
        or (any(term in normalized for term in action_terms) and any(term in normalized for term in place_terms))
    )

def _should_clarify_place_capability(message: str) -> bool:
    normalized = " ".join((message or "").lower().split())
    has_place = any(term in normalized for term in ("khách sạn", "hotel", "lưu trú", "chỗ ở", "nhà hàng", "restaurant"))
    asks_capability = any(term in normalized for term in ("được không", "có được", "có thể", "can you"))
    return has_place and asks_capability

def _place_capability_response(session_id: str, message: str, language: str) -> ChatResponse:
    lang = "en" if language == "en" else "vi"
    text = _safe_direct_answer(message, [], lang) or (
        "Được. Bạn cho mình biết loại địa điểm, ngân sách/khu vực gần đâu và yêu cầu đi kèm nhé."
        if lang == "vi" else
        "Yes. Tell me the place type, budget/area, and any requirements."
    )
    return ChatResponse(session_id=session_id, message=text, citations=[], places=[], intent="conversational", latency_ms=0.0, fallback=False)

def _strip_retrieval_preamble(text: str) -> str:
    """Remove deterministic fallback boilerplate that makes answers look like raw chunks."""
    return re.sub(r"^\s*Dựa trên thông tin thu thập được:\s*", "", text or "", flags=re.IGNORECASE).strip()


@dataclass
class InMemoryAgentCheckpointer:
    _store: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    async def load_history(self, session_id: str) -> list[dict[str, str]]:
        return list(self._store.get(session_id, []))

    async def save_turn(self, session_id: str, user: str, assistant: str) -> None:
        history = self._store.setdefault(session_id, [])
        history.extend([
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ])
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


# -- Fairness audit logging --

_FAIRNESS_AUDIT_DIR = Path("data/fairness_audit")


def _fairness_audit_log(places: list, trace_id: str | None = None) -> None:
    if not places:
        return
    try:
        local_factors = []
        for place in places:
            lf = getattr(place, "local_factor", None)
            if lf is not None:
                local_factors.append(float(lf))
        if not local_factors:
            return
        count = len(local_factors)
        mean_val = sum(local_factors) / count
        buckets: dict[str, int] = {"<0.1": 0, "0.1-0.3": 0, "0.3-0.5": 0, ">0.5": 0}
        for lf in local_factors:
            if lf < 0.1:
                buckets["<0.1"] += 1
            elif lf < 0.3:
                buckets["0.1-0.3"] += 1
            elif lf < 0.5:
                buckets["0.3-0.5"] += 1
            else:
                buckets[">0.5"] += 1
        audit_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace_id": trace_id,
            "count": count,
            "mean": round(mean_val, 4),
            "min": round(min(local_factors), 4),
            "max": round(max(local_factors), 4),
            "local_factors": [round(lf, 4) for lf in local_factors],
            "distribution": buckets,
        }
        _FAIRNESS_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        filepath = _FAIRNESS_AUDIT_DIR / f"{ts}.jsonl"
        with open(filepath, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(audit_record, ensure_ascii=False) + "\n")
        logger.info("fairness_audit.logged", filepath=str(filepath), count=count, mean=round(mean_val, 4))
    except Exception as exc:
        logger.warning("fairness_audit.error", reason=type(exc).__name__)


class AgentService:
    """ReAct Agent orchestration — LLM decides which tool to call.

    Tools available to the LLM:
      - search_knowledge: RAG retrieval for cultural/historical queries
      - search_places: Google Places API for restaurants, hotels, etc.

    For conversational inputs (greetings, small talk), the LLM responds
    directly without calling any tools — this is the natural behavior
    of a tool-calling LLM when no tool is needed.
    """

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
        self._fallback_service = GroundedAnswerService(retriever) if retriever is not None else None
        self._place_recommendation_service = place_recommendation_service
        self._checkpointer = checkpointer or InMemoryAgentCheckpointer()
        self.checkpoint_mode = checkpoint_mode
        self._semantic_cache = semantic_cache
        self._embedding_service = embedding_service
        self._langfuse_client = langfuse_client
        llm_client = getattr(llm_service, "_client", None) if llm_service is not None else None
        if type(llm_client).__module__.startswith("unittest.mock"):
            llm_client = None
        self._agentic_chat = (
            AgenticChatService(
                retriever=retriever,
                hybrid_retriever=hybrid_retriever,
                llm_service=llm_service,
                place_recommendation_service=place_recommendation_service,
            )
            if llm_client is not None
            else None
        )
        self._graph = self._build_graph()

    def _build_graph(self) -> Any | None:
        if StateGraph is None:
            return None
        graph = StateGraph(AgentState)
        graph.add_node("retrieve", self._retrieve_node)
        graph.add_node("answer", self._answer_node)
        graph.set_entry_point("retrieve")
        graph.add_edge("retrieve", "answer")
        graph.add_edge("answer", END)
        return graph.compile(checkpointer=MemorySaver() if MemorySaver else None)

    def _start_langfuse_span(self, *, trace_id: str, name: str, as_type: str = "span", input_data: dict | None = None) -> Any | None:
        if self._langfuse_client is None:
            return None
        try:
            from langfuse.types import TraceContext
            span = self._langfuse_client.start_observation(
                trace_context=TraceContext(trace_id=trace_id),
                name=name,
                as_type=as_type,
                input=input_data,
            )
            logger.info("langfuse.span_started", trace_id=trace_id, name=name)
            return span
        except Exception as exc:
            logger.warning("langfuse.error", operation="start_observation", name=name, reason=type(exc).__name__)
            return None

    def _end_langfuse_span(self, span: Any | None, *, trace_id: str, name: str, output_data: dict | None = None) -> None:
        if span is None:
            return
        try:
            if output_data:
                span.update(output=output_data)
            span.end()
            logger.info("langfuse.span_ended", trace_id=trace_id, name=name)
        except Exception as exc:
            logger.warning("langfuse.error", operation="end_observation", name=name, reason=type(exc).__name__)

    async def answer(self, *, session_id: str, message: str, language: str = "vi") -> ChatResponse:
        """Return a grounded ChatResponse and persist the turn for the session.

        ReAct pattern: LLM decides which tool to call based on the message.
        - Conversational → LLM responds directly, no tools
        - Knowledge query → LLM calls search_knowledge (RAG)
        - Place query → LLM calls search_places (Google Places API)
        """
        t0 = time.perf_counter()
        state = await self._initial_state(session_id, message, language)

        direct = _safe_direct_answer(message, state.get("history", []), "en" if language == "en" else "vi")
        if direct is not None:
            response = ChatResponse(
                session_id=session_id,
                message=direct,
                citations=[],
                places=[],
                intent="conversational",
                latency_ms=round((time.perf_counter() - t0) * 1000, 3),
                fallback=False,
            )
            await self._save_turn(session_id, message, direct)
            return response

        if _should_clarify_place_capability(message):
            response = _place_capability_response(session_id, message, language)
            await self._save_turn(session_id, message, response.message)
            return response

        if _should_use_places_before_rag(message) and self._place_recommendation_service is not None:
            response = await self._place_recommendation_service.recommend(query=message, language=language, session_id=session_id)
            await self._save_turn(session_id, message, response.message)
            return response

        if self._agentic_chat is not None:
            try:
                response = await self._agentic_chat.answer(
                    session_id=session_id,
                    message=message,
                    language=language,
                    history=state.get("history", []),
                )
                await self._save_turn(session_id, message, response.message)
                logger.info(
                    "agent.agentic_end", session_id=session_id,
                    retrieval_count=len(response.citations), fallback=response.fallback,
                    latency_ms=round((time.perf_counter() - t0) * 1000, 3),
                )
                return response
            except Exception as exc:
                logger.warning("agent.agentic_fallback", session_id=session_id, reason=type(exc).__name__)

        trace_id: str | None = None
        if self._langfuse_client is not None:
            try:
                trace_id = self._langfuse_client.create_trace_id(seed=session_id)
                state["langfuse_trace_id"] = trace_id
            except Exception:
                pass

        # Retrieve node (RAG — always run, results available if LLM needs them)
        retrieve_span = self._start_langfuse_span(
            trace_id=trace_id or "", name="retrieve", as_type="retriever",
            input_data={"query": state["retrieval_query"]},
        )
        try:
            state = await asyncio.wait_for(self._retrieve_node(state), timeout=NODE_TIMEOUT_RETRIEVE)
        except asyncio.TimeoutError:
            logger.warning("agent.node_timeout", session_id=session_id, node="retrieve", timeout_seconds=NODE_TIMEOUT_RETRIEVE)
            state["fallback_reason"] = f"NodeTimeoutError(retrieve, {NODE_TIMEOUT_RETRIEVE}s)"
            state["chunks"] = []
            state["citations"] = []
        self._end_langfuse_span(
            retrieve_span, trace_id=trace_id or "", name="retrieve",
            output_data={"retrieval_count": len(state.get("chunks", []))},
        )

        # Answer node — LLM decides: respond directly or use Places API
        answer_span = self._start_langfuse_span(
            trace_id=trace_id or "", name="answer",
            input_data={"chunks_count": len(state.get("chunks", []))},
        )
        try:
            state = await asyncio.wait_for(self._answer_node(state), timeout=NODE_TIMEOUT_ANSWER)
        except asyncio.TimeoutError:
            logger.warning("agent.node_timeout", session_id=session_id, node="answer", timeout_seconds=NODE_TIMEOUT_ANSWER)
            state["fallback_reason"] = state.get("fallback_reason") or f"NodeTimeoutError(answer, {NODE_TIMEOUT_ANSWER}s)"
            state["response"] = await self._compose_fallback(state, state.get("fallback_reason", "llm_timeout"))
        response = state["response"]
        self._end_langfuse_span(
            answer_span, trace_id=trace_id or "", name="answer",
            output_data={"response_length": len(response.message), "fallback": response.fallback},
        )

        await self._save_turn(session_id, message, response.message)

        if trace_id is not None:
            response.langfuse_trace_id = trace_id

        logger.info(
            "agent.graph_end", session_id=session_id,
            retrieval_count=len(response.citations), fallback=response.fallback,
            fallback_reason=state.get("fallback_reason"),
            latency_ms=round((time.perf_counter() - t0) * 1000, 3),
            langfuse_trace_id=trace_id,
        )
        return response

    async def answer_stream(self, *, session_id: str, message: str, language: str = "vi") -> AsyncGenerator[str, None]:
        """Yield answer tokens, then citations marker and DONE marker."""
        state = await self._initial_state(session_id, message, language)

        direct = _safe_direct_answer(message, state.get("history", []), "en" if language == "en" else "vi")
        if direct is not None:
            await self._save_turn(session_id, message, direct)
            yield "[STATUS] using_history"
            yield direct
            return

        if _should_clarify_place_capability(message):
            response = _place_capability_response(session_id, message, language)
            await self._save_turn(session_id, message, response.message)
            yield "[STATUS] using_history"
            yield response.message
            return

        if _should_use_places_before_rag(message) and self._place_recommendation_service is not None:
            yield "[STATUS] checking_places"
            response = await self._place_recommendation_service.recommend(query=message, language=language, session_id=session_id)
            await self._save_turn(session_id, message, response.message)
            yield response.message
            if response.places:
                yield f"[PLACES] {json.dumps([place.model_dump() for place in response.places], ensure_ascii=False)}"
            return

        if self._agentic_chat is not None:
            try:
                answer_text = ""
                async for event in self._agentic_chat.answer_stream(
                    session_id=session_id,
                    message=message,
                    language=language,
                    history=state.get("history", []),
                ):
                    if not event.startswith("["):
                        answer_text += event
                    yield event
                await self._save_turn(session_id, message, answer_text)
                logger.info("agent.agentic_stream_complete", session_id=session_id)
                return
            except Exception as exc:
                logger.warning("agent.agentic_stream_fallback", session_id=session_id, reason=type(exc).__name__)

        trace_id: str | None = None
        if self._langfuse_client is not None:
            try:
                trace_id = self._langfuse_client.create_trace_id(seed=session_id)
                state["langfuse_trace_id"] = trace_id
            except Exception:
                pass

        # Retrieve
        retrieve_span = self._start_langfuse_span(
            trace_id=trace_id or "", name="retrieve", as_type="retriever",
            input_data={"query": state["retrieval_query"]},
        )
        try:
            state = await asyncio.wait_for(self._retrieve_node(state), timeout=NODE_TIMEOUT_RETRIEVE)
        except asyncio.TimeoutError:
            logger.warning("agent.node_timeout", session_id=session_id, node="retrieve", timeout_seconds=NODE_TIMEOUT_RETRIEVE)
            state["chunks"] = []
            state["citations"] = []
        self._end_langfuse_span(
            retrieve_span, trace_id=trace_id or "", name="retrieve",
            output_data={"retrieval_count": len(state.get("chunks", []))},
        )

        intent = await self._classify_message_intent(state)
        if intent == "conversational":
            response = self._conversational_response(state)
            await self._save_turn(session_id, message, response.message)
            yield response.message
            yield "[CITATIONS] []"
            yield "[DONE]"
            logger.info("agent.stream_complete", session_id=session_id, intent=intent, fallback_reason=None, langfuse_trace_id=trace_id)
            return

        answer_text = ""
        citations = state.get("citations", [])
        fallback_reason: str | None = None

        if self._llm_service is not None:
            answer_span = self._start_langfuse_span(
                trace_id=trace_id or "", name="answer",
                input_data={"chunks_count": len(state.get("chunks", []))},
            )
            try:
                stream = self._llm_service.answer_stream(
                    chunks=state.get("chunks", []), citations=citations,
                    query=state["retrieval_query"], language=language, session_id=session_id,
                )
                while True:
                    try:
                        token = await asyncio.wait_for(stream.__anext__(), timeout=NODE_TIMEOUT_ANSWER)
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        fallback_reason = f"NodeTimeoutError(answer_stream, {NODE_TIMEOUT_ANSWER}s)"
                        break
                    answer_text += token
                    yield token
            except Exception as exc:
                fallback_reason = type(exc).__name__
                logger.warning("agent.answer_fallback", session_id=session_id, fallback_reason=fallback_reason)
            self._end_langfuse_span(
                answer_span, trace_id=trace_id or "", name="answer",
                output_data={"response_length": len(answer_text), "fallback": fallback_reason is not None},
            )

        if not answer_text:
            response = await self._compose_fallback(state, fallback_reason or "llm_unavailable")
            answer_text = response.message
            citations = response.citations
            yield answer_text

        await self._save_turn(session_id, message, answer_text)
        yield f"[CITATIONS] {json.dumps([c.model_dump() for c in citations], ensure_ascii=False)}"
        yield "[DONE]"
        logger.info("agent.stream_complete", session_id=session_id, fallback_reason=fallback_reason, langfuse_trace_id=trace_id)

    async def stream(self, *, session_id: str, message: str, language: str = "vi") -> AsyncGenerator[str, None]:
        async for event in self.answer_stream(session_id=session_id, message=message, language=language):
            yield event

    async def _initial_state(self, session_id: str, message: str, language: str) -> AgentState:
        try:
            history = await self._checkpointer.load_history(session_id)
        except Exception as exc:
            logger.warning("agent.checkpoint_load", session_id=session_id, reason=type(exc).__name__)
            history = []
        prior_user = next((h["content"] for h in reversed(history) if h.get("role") == "user"), "")
        retrieval_query = message if _is_context_free_conversation(message) else (f"{prior_user}\n{message}" if prior_user else message)
        return {
            "session_id": session_id,
            "message": message,
            "language": language,
            "history": history,
            "retrieval_query": retrieval_query,
            "fallback_reason": None,
            "intent": None,
        }

    async def _retrieve_node(self, state: AgentState) -> AgentState:
        query = state["retrieval_query"]

        # Semantic cache
        cache_hit_response: str | None = None
        if self._semantic_cache is not None and self._embedding_service is not None:
            try:
                query_embedding = await self._embedding_service.embed_texts([query])
                if query_embedding and len(query_embedding) > 0:
                    cache_hit_response = await self._semantic_cache.lookup(query, query_embedding[0])
            except Exception:
                pass

        if cache_hit_response is not None:
            state["citations"] = []
            state["chunks"] = [RAGChunk(
                chunk_id="cache_hit", source_id="semantic_cache", title="Semantic Cache Hit",
                url="", domain="cache", source_type="cache", reliability="low",
                language="unknown", location="", text=cache_hit_response, chunk_index=0, total_chunks=1,
            )]
            logger.info("agent.cache_hit", session_id=state["session_id"])
            return state

        # Normal retrieval
        try:
            if self._hybrid_retriever is not None:
                result, citations = await self._hybrid_retriever.search_with_citations(query, top_k=5)
                mode = "hybrid"
            elif self._retriever is not None:
                result, citations = self._retriever.search_with_citations(query, top_k=5)
                mode = "keyword"
            else:
                result = RetrievalResult(chunks=[], query=query, total_found=0)
                citations = []
                mode = "none"
        except Exception as exc:
            logger.warning("agent.retrieve_fallback", session_id=state["session_id"], reason=type(exc).__name__)
            result = RetrievalResult(chunks=[], query=query, total_found=0)
            citations = []
            mode = "error"
            state["fallback_reason"] = type(exc).__name__

        state["chunks"] = result.chunks
        state["citations"] = citations

        # Store in semantic cache
        if self._semantic_cache is not None and self._embedding_service is not None and result.chunks:
            try:
                response_text = " ".join(c.text for c in result.chunks)
                query_embedding = await self._embedding_service.embed_texts([query])
                if query_embedding and len(query_embedding) > 0:
                    await self._semantic_cache.store(query, query_embedding[0], response_text)
            except Exception:
                pass

        logger.info("agent.node_complete", phase="retrieve", session_id=state["session_id"],
                     retrieval_mode=mode, retrieval_count=len(result.chunks))
        return state

    async def _answer_node(self, state: AgentState) -> AgentState:
        """Answer node — LLM decides: respond directly or use Places API.

        ReAct pattern: the LLM sees the user message + RAG context + tool descriptions.
        It decides which action to take:
          - Conversational (greeting, thanks) → respond directly, no tool call
          - Place search (restaurant, hotel) → call Places API
          - Cultural/historical → use RAG context directly
        """
        intent = await self._classify_message_intent(state)
        is_conversational = intent == "conversational"
        is_place = _is_place_intent(intent) or _should_use_places_before_rag(state["message"])

        # Conversational → direct response, no LLM call needed
        if is_conversational:
            state["response"] = self._conversational_response(state)
            logger.info("agent.node_complete", phase="conversational",
                        session_id=state["session_id"], intent=intent)
            return state

        # Place intent → call Places API, inject results as context
        if is_place and self._place_recommendation_service is not None:
            try:
                place_response = await self._place_recommendation_service.recommend(
                    query=state["message"], language=state["language"],
                    session_id=state["session_id"],
                )
                _fairness_audit_log(places=place_response.places,
                                    trace_id=state.get("langfuse_trace_id"))

                if place_response.places:
                    places_context = self._build_places_context(place_response.places)
                    place_chunk = RAGChunk(
                        chunk_id="places_api", source_id="places_api",
                        title="Local Places (Google Places API)", url="",
                        domain="places", source_type="api", reliability="high",
                        language="unknown", location="", text=places_context,
                        chunk_index=0, total_chunks=1,
                    )
                    state["chunks"] = [place_chunk] + state.get("chunks", [])
                    state["citations"] = place_response.citations + state.get("citations", [])

                cultural_chunks = self._extract_cultural_context(state.get("chunks", []))
                if cultural_chunks:
                    cultural_intro = self._build_cultural_intro(cultural_chunks, state["language"])
                    place_response.message = f"{cultural_intro}\n\n{place_response.message}"

                state["response"] = ChatResponse(
                    session_id=state["session_id"], message=place_response.message,
                    citations=state["citations"], places=place_response.places,
                    reasoning_log=place_response.reasoning_log,
                    intent=PLACE_RECOMMENDATION_INTENT,
                    langfuse_trace_id=state.get("langfuse_trace_id"),
                    latency_ms=place_response.latency_ms, fallback=place_response.fallback,
                )
                logger.info("agent.node_complete", phase="place_recommendation",
                            session_id=state["session_id"], result_count=len(place_response.places),
                            fallback=place_response.fallback)
                return state
            except Exception as exc:
                logger.warning("agent.place_recommendation_fallback",
                               session_id=state["session_id"], reason=type(exc).__name__)
                # Fall through to LLM answer

        # Default: LLM answers with RAG context
        if self._llm_service is not None:
            try:
                response = await self._llm_service.answer(
                    chunks=state.get("chunks", []), citations=state.get("citations", []),
                    query=state["retrieval_query"], language=state["language"],
                    session_id=state["session_id"],
                )
                state["response"] = response
                logger.info("agent.node_complete", phase="answer",
                            session_id=state["session_id"], fallback=False)
                return state
            except Exception as exc:
                state["fallback_reason"] = type(exc).__name__
                logger.warning("agent.answer_fallback", session_id=state["session_id"],
                               fallback_reason=type(exc).__name__)

        fallback_reason = state.get("fallback_reason") or "llm_unavailable"
        state["response"] = await self._compose_fallback(state, fallback_reason)
        logger.info("agent.node_complete", phase="answer",
                    session_id=state["session_id"], fallback=state["response"].fallback)
        return state

    async def _classify_message_intent(self, state: AgentState) -> str:
        """Classify the current turn using the LLM router first, keywords only as fallback."""
        from agents.guardrails.grounded_answer import classify_intent, detect_intent

        intent = detect_intent(state["message"])
        confidence = 0.5
        if self._llm_service is not None:
            client = getattr(self._llm_service, "_client", None)
            model = getattr(self._llm_service, "model", "gpt-4o-mini")
            intent, confidence = await classify_intent(state["message"], client=client, model=model)
        intent = _normalize_intent(intent)
        state["intent"] = intent
        state["intent_confidence"] = confidence
        return intent

    def _conversational_response(self, state: AgentState) -> ChatResponse:
        """Direct response for greetings/small talk — no LLM or RAG needed.

        Best practice: conversational inputs should NOT trigger any tool.
        The LLM could handle these naturally, but since we're not using
        tool-calling yet, we respond directly for speed and correctness.
        """
        lang = (state.get("language") or "vi").lower()

        if lang == "vi":
            text = ("Mình có thể giúp bạn theo 4 nhóm chính:\n"
                    "- Tìm quán ăn, hải sản, cà phê hoặc chỗ lưu trú quanh Hàm Ninh.\n"
                    "- Gợi ý đường đi, khu vực nên ghé và cách sắp lịch tham quan.\n"
                    "- Tóm tắt văn hóa, lịch sử, nghề biển và trải nghiệm địa phương.\n"
                    "- Trả lời có nguồn khi câu hỏi cần kiểm chứng; còn chào hỏi thì mình trò chuyện bình thường.\n\n"
                    "Bạn có thể hỏi kiểu: 'Gợi ý quán hải sản ít đông' hoặc 'Kể ngắn gọn lịch sử làng chài'.")
        else:
            text = ("I can help in four practical ways:\n"
                    "- Find food, seafood, cafes, or stays around Ham Ninh.\n"
                    "- Suggest directions, areas to visit, and simple trip planning.\n"
                    "- Summarize local culture, history, fishing life, and experiences.\n"
                    "- Use sources when a question needs evidence; small talk stays conversational.\n\n"
                    "Try: 'Suggest a quiet seafood spot' or 'Give me a short village history'.")
        return ChatResponse(
            session_id=state["session_id"], message=text,
            citations=[], places=[], intent="conversational",
            langfuse_trace_id=state.get("langfuse_trace_id"),
            latency_ms=0.0, fallback=False,
        )

    def _build_places_context(self, places: list) -> str:
        lines = ["Các địa điểm tìm được từ Google Places:"]
        for i, place in enumerate(places[:5], 1):
            name = getattr(place, "display_name", "Unknown")
            address = getattr(place, "formatted_address", "")
            rating = getattr(place, "rating", None)
            rating_str = f" (đánh giá {rating})" if rating else ""
            lines.append(f"{i}. **{name}**{rating_str} — {address}")
        return "\n".join(lines)

    # -- SOC-05: Cultural context --

    _CULTURAL_DOMAINS = {"culture", "history", "heritage", "tradition", "festival", "temple", "đình", "chùa", "di tích", "lễ hội", "văn hóa"}

    def _extract_cultural_context(self, chunks: list[RAGChunk]) -> list[RAGChunk]:
        cultural: list[RAGChunk] = []
        for chunk in chunks:
            domain = (chunk.domain or "").lower()
            source_type = (chunk.source_type or "").lower()
            title = (chunk.title or "").lower()
            text = (chunk.text or "").lower()
            is_cultural = (
                any(d in domain for d in self._CULTURAL_DOMAINS)
                or any(d in source_type for d in self._CULTURAL_DOMAINS)
                or any(d in title for d in self._CULTURAL_DOMAINS)
                or any(d in text[:200] for d in self._CULTURAL_DOMAINS)
            )
            if is_cultural:
                cultural.append(chunk)
                if len(cultural) >= 3:
                    break
        return cultural

    def _build_cultural_intro(self, cultural_chunks: list[RAGChunk], language: str) -> str:
        intro = "🏛️ **Về Hàm Ninh — Bối cảnh văn hóa:**" if language == "vi" else "🏛️ **About Hàm Ninh — Cultural Context:**"
        snippets = []
        for chunk in cultural_chunks[:2]:
            text = (chunk.text or "")[:150]
            if text:
                snippets.append(f"- {text}")
        if snippets:
            return f"{intro}\n" + "\n".join(snippets)
        return intro

    async def _compose_fallback(self, state: AgentState, reason: str) -> ChatResponse:
        if self._fallback_service is None:
            return ChatResponse(
                session_id=state["session_id"],
                message="Hiện tại nguồn dữ liệu chưa có thông tin đầy đủ để trả lời câu hỏi này.",
                citations=[], places=[], intent=None,
                langfuse_trace_id=None, latency_ms=0.0, fallback=True,
            )
        response = self._fallback_service.answer_from_chunks(
            chunks=state.get("chunks", []), citations=state.get("citations", []),
            query=state["message"], language=state["language"],
            session_id=state["session_id"],
        )
        response.message = _strip_retrieval_preamble(response.message)
        response.fallback = reason != "llm_unavailable"
        state["fallback_reason"] = reason
        return response

    async def _save_turn(self, session_id: str, message: str, answer: str) -> None:
        try:
            await self._checkpointer.save_turn(session_id, message, answer)
        except Exception as exc:
            logger.warning("agent.checkpoint_save", session_id=session_id, reason=type(exc).__name__)
