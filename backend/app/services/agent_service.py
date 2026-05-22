"""LangGraph-backed chat agent orchestration with per-session memory.

AgentService is the shared backend boundary for non-streaming and streaming chat.
It owns retrieval, LLM fallback, citation preservation, and lightweight session
state so routers do not duplicate orchestration logic.
"""

from __future__ import annotations

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
from app.services.grounded_answer import GroundedAnswerService, detect_intent
from app.services.retriever import Retriever
from app.services.place_recommendation_service import PLACE_RECOMMENDATION_INTENT

try:  # LangGraph is optional in unit tests until dependencies are installed.
    from langgraph.graph import END, StateGraph
    from langgraph.checkpoint.memory import MemorySaver
except Exception:  # pragma: no cover - exercised when dependency is absent locally.
    END = "__end__"
    StateGraph = None  # type: ignore[assignment]
    MemorySaver = None  # type: ignore[assignment]

logger = structlog.get_logger(__name__)


class AgentState(TypedDict, total=False):
    """Serializable state passed through the retrieval and answer phases."""

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


@dataclass
class InMemoryAgentCheckpointer:
    """Small async checkpointer used when Postgres/LangGraph persistence is absent."""

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
    """Asyncpg-backed checkpointer matching AgentService's session history contract."""

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
                """
                CREATE TABLE IF NOT EXISTS agent_session_messages (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_session_messages_session_order
                ON agent_session_messages (session_id, id)
                """
            )

    async def load_history(self, session_id: str) -> list[dict[str, str]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT role, content
                FROM (
                    SELECT id, role, content
                    FROM agent_session_messages
                    WHERE session_id = $1
                    ORDER BY id DESC
                    LIMIT 8
                ) recent
                ORDER BY id ASC
                """,
                session_id,
            )
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    async def save_turn(self, session_id: str, user: str, assistant: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO agent_session_messages (session_id, role, content)
                VALUES ($1, $2, $3)
                """,
                [(session_id, "user", user), (session_id, "assistant", assistant)],
            )

async def create_agent_checkpointer(database_url: str | None = None) -> tuple[Any, str]:
    """Create a checkpoint backend, falling back to memory when unavailable.

    Returns a tuple of (checkpointer, checkpoint_mode). The in-memory fallback
    keeps local and test execution working when DATABASE_URL/Postgres is absent.
    """
    dsn = database_url or os.getenv("DATABASE_URL")
    if dsn:
        try:
            return await PostgresAgentCheckpointer.create(dsn), "postgres"
        except Exception as exc:
            logger.warning(
                "agent.checkpoint_init_failed",
                checkpoint_mode="memory",
                reason=type(exc).__name__,
            )
    return InMemoryAgentCheckpointer(), "memory"


class AgentService:
    """Shared agent orchestration for POST and SSE chat flows."""

    def __init__(
        self,
        *,
        retriever: Retriever | None,
        hybrid_retriever: Any | None = None,
        llm_service: Any | None = None,
        checkpointer: Any | None = None,
        checkpoint_mode: Literal["memory", "postgres", "test"] = "memory",
        place_recommendation_service: Any | None = None,
    ) -> None:
        self._retriever = retriever
        self._hybrid_retriever = hybrid_retriever
        self._llm_service = llm_service
        self._fallback_service = GroundedAnswerService(retriever) if retriever is not None else None
        self._place_recommendation_service = place_recommendation_service
        self._checkpointer = checkpointer or InMemoryAgentCheckpointer()
        self.checkpoint_mode = checkpoint_mode
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

    async def answer(self, *, session_id: str, message: str, language: str = "vi") -> ChatResponse:
        """Return a grounded ChatResponse and persist the turn for the session."""
        t0 = time.perf_counter()
        state = await self._initial_state(session_id, message, language)
        logger.info(
            "agent.graph_start",
            session_id=session_id,
            checkpoint_mode=self.checkpoint_mode,
            stream=False,
            history_turns=len(state.get("history", [])) // 2,
        )
        state = await self._retrieve_node(state)
        state = await self._answer_node(state)
        response = state["response"]
        await self._save_turn(session_id, message, response.message)
        logger.info(
            "agent.graph_end",
            session_id=session_id,
            retrieval_count=len(response.citations),
            fallback=response.fallback,
            fallback_reason=state.get("fallback_reason"),
            latency_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
        return response

    async def answer_stream(
        self, *, session_id: str, message: str, language: str = "vi"
    ) -> AsyncGenerator[str, None]:
        """Yield answer tokens, then a citations marker and DONE marker."""
        state = await self._initial_state(session_id, message, language)
        state = await self._retrieve_node(state)
        answer_text = ""
        citations = state.get("citations", [])
        fallback_reason: str | None = None

        logger.info(
            "agent.stream_start",
            session_id=session_id,
            checkpoint_mode=self.checkpoint_mode,
            retrieval_count=len(citations),
        )
        if self._is_place_intent(state):
            response = await self._answer_place_intent(state)
            answer_text = response.message
            citations = response.citations
            yield answer_text
            logger.info(
                "agent.stream_place_recommendation",
                session_id=session_id,
                result_count=len(response.places),
                fallback=response.fallback,
            )
        elif self._llm_service is not None:
            try:
                async for token in self._llm_service.answer_stream(
                    chunks=state.get("chunks", []),
                    citations=citations,
                    query=state["retrieval_query"],
                    language=language,
                    session_id=session_id,
                ):
                    answer_text += token
                    yield token
            except Exception as exc:
                fallback_reason = type(exc).__name__
                logger.warning("agent.answer_fallback", session_id=session_id, fallback_reason=fallback_reason)

        if not answer_text:
            response = await self._compose_fallback(state, fallback_reason or "llm_unavailable")
            answer_text = response.message
            citations = response.citations
            yield answer_text

        await self._save_turn(session_id, message, answer_text)
        yield f"[CITATIONS] {json.dumps([c.model_dump() for c in citations], ensure_ascii=False)}"
        yield "[DONE]"
        logger.info("agent.stream_complete", session_id=session_id, fallback_reason=fallback_reason)


    async def stream(
        self, *, session_id: str, message: str, language: str = "vi"
    ) -> AsyncGenerator[str, None]:
        """Backward-compatible alias for older internal callers."""
        async for event in self.answer_stream(session_id=session_id, message=message, language=language):
            yield event

    async def _initial_state(self, session_id: str, message: str, language: str) -> AgentState:
        try:
            history = await self._checkpointer.load_history(session_id)
        except Exception as exc:
            logger.warning("agent.checkpoint_load", session_id=session_id, reason=type(exc).__name__)
            history = []
        prior_user = next((h["content"] for h in reversed(history) if h.get("role") == "user"), "")
        retrieval_query = f"{prior_user}\n{message}" if prior_user else message
        return {
            "session_id": session_id,
            "message": message,
            "language": language,
            "history": history,
            "retrieval_query": retrieval_query,
            "fallback_reason": None,
            "intent": detect_intent(message),
        }

    async def _retrieve_node(self, state: AgentState) -> AgentState:
        query = state["retrieval_query"]
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
        logger.info(
            "agent.node_complete",
            phase="retrieve",
            session_id=state["session_id"],
            retrieval_mode=mode,
            retrieval_count=len(result.chunks),
        )
        return state

    async def _answer_node(self, state: AgentState) -> AgentState:
        if self._is_place_intent(state):
            state["response"] = await self._answer_place_intent(state)
            logger.info(
                "agent.node_complete",
                phase="place_recommendation",
                session_id=state["session_id"],
                intent=state.get("intent"),
                result_count=len(state["response"].places),
                fallback=state["response"].fallback,
            )
            return state

        if self._llm_service is not None:
            try:
                response = await self._llm_service.answer(
                    chunks=state.get("chunks", []),
                    citations=state.get("citations", []),
                    query=state["retrieval_query"],
                    language=state["language"],
                    session_id=state["session_id"],
                )
                state["response"] = response
                logger.info("agent.node_complete", phase="answer", session_id=state["session_id"], fallback=False)
                return state
            except Exception as exc:
                state["fallback_reason"] = type(exc).__name__
                logger.warning("agent.answer_fallback", session_id=state["session_id"], fallback_reason=type(exc).__name__)

        fallback_reason = state.get("fallback_reason") or "llm_unavailable"
        state["response"] = await self._compose_fallback(state, fallback_reason)
        logger.info(
            "agent.node_complete",
            phase="answer",
            session_id=state["session_id"],
            fallback=state["response"].fallback,
        )
        return state

    def _is_place_intent(self, state: AgentState) -> bool:
        intent = state.get("intent") or detect_intent(state["message"])
        if intent == "navigation":
            return True
        lower = state["message"].lower()
        dynamic_place_terms = (
            "đang mở",
            "mở cửa",
            "giờ mở",
            "giờ đóng",
            "đánh giá",
            "rating",
            "review",
            "địa chỉ",
            "address",
            "số điện thoại",
            "điện thoại",
            "phone",
            "website",
            "google maps",
            "bản đồ",
            "near me",
            "gần tôi",
            "hiện tại",
            "chi tiết",
            "details",
        )
        if intent == "restaurant_search":
            return any(term in lower for term in dynamic_place_terms)

        recommendation_terms = ("recommend", "gợi ý", "đề xuất", "dịch vụ", "service", "place", "địa điểm")
        ham_ninh_terms = ("hàm ninh", "ham ninh")
        return any(term in lower for term in recommendation_terms) and any(term in lower for term in ham_ninh_terms)

    async def _answer_place_intent(self, state: AgentState) -> ChatResponse:
        if self._place_recommendation_service is None:
            state["fallback_reason"] = "place_recommendation_unavailable"
            return ChatResponse(
                session_id=state["session_id"],
                message="Place recommendations are unavailable because the server Places service is not configured.",
                citations=[],
                places=[],
                reasoning_log="place_recommendation status=unavailable source=none candidate_count=0 result_count=0",
                intent=PLACE_RECOMMENDATION_INTENT,
                langfuse_trace_id=None,
                latency_ms=0.0,
                fallback=True,
            )
        try:
            return await self._place_recommendation_service.recommend(
                query=state["message"],
                language=state["language"],
                session_id=state["session_id"],
            )
        except Exception as exc:  # noqa: BLE001 - service boundary must fail closed.
            state["fallback_reason"] = "place_recommendation_error"
            logger.warning(
                "agent.place_recommendation_fallback",
                session_id=state["session_id"],
                reason=type(exc).__name__,
            )
            return ChatResponse(
                session_id=state["session_id"],
                message="Place recommendations are temporarily unavailable. Please try again shortly.",
                citations=[],
                places=[],
                reasoning_log="place_recommendation status=upstream_error source=none candidate_count=0 result_count=0",
                intent=PLACE_RECOMMENDATION_INTENT,
                langfuse_trace_id=None,
                latency_ms=0.0,
                fallback=True,
            )

    async def _compose_fallback(self, state: AgentState, reason: str) -> ChatResponse:
        if self._fallback_service is None:
            return ChatResponse(
                session_id=state["session_id"],
                message="Hiện tại nguồn dữ liệu chưa có thông tin đầy đủ để trả lời câu hỏi này.",
                citations=[],
                places=[],
                intent=None,
                langfuse_trace_id=None,
                latency_ms=0.0,
                fallback=True,
            )
        response = self._fallback_service.answer_from_chunks(
            chunks=state.get("chunks", []),
            citations=state.get("citations", []),
            query=state["message"],
            language=state["language"],
            session_id=state["session_id"],
        )
        response.fallback = reason != "llm_unavailable"
        state["fallback_reason"] = reason
        return response

    async def _save_turn(self, session_id: str, message: str, answer: str) -> None:
        try:
            await self._checkpointer.save_turn(session_id, message, answer)
        except Exception as exc:
            logger.warning("agent.checkpoint_save", session_id=session_id, reason=type(exc).__name__)
