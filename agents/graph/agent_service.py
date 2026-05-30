"""LangGraph-backed chat agent orchestration with per-session memory.

AgentService is the shared backend boundary for non-streaming and streaming chat.
It owns retrieval, LLM fallback, citation preservation, and lightweight session
state so routers do not duplicate orchestration logic.
"""

from __future__ import annotations

import asyncio
import json
import os
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
from agents.guardrails.grounded_answer import GroundedAnswerService, detect_intent, classify_intent
from agents.tools.retriever import Retriever
from agents.services.place_recommendation_service import PLACE_RECOMMENDATION_INTENT

try:  # LangGraph is optional in unit tests until dependencies are installed.
    from langgraph.graph import END, StateGraph
    from langgraph.checkpoint.memory import MemorySaver
except Exception:  # pragma: no cover - exercised when dependency is absent locally.
    END = "__end__"
    StateGraph = None  # type: ignore[assignment]
    MemorySaver = None  # type: ignore[assignment]

logger = structlog.get_logger(__name__)

# -- Per-node timeout thresholds (ROB-06) --
NODE_TIMEOUT_RETRIEVE = 10  # seconds for retrieval node
NODE_TIMEOUT_ANSWER = 15    # seconds for answer generation node


class NodeTimeoutError(Exception):
    """Raised when a graph node exceeds its configured timeout.

    Captures the node name and timeout value for structured logging
    and user-friendly error messages.
    """

    def __init__(self, node_name: str, timeout_seconds: int) -> None:
        self.node_name = node_name
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Node '{node_name}' timed out after {timeout_seconds}s")


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
    langfuse_trace_id: str | None


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
        self._graph = self._build_graph()

        # Extract OpenAI client from LLM service for intent classification
        self._intent_client: Any | None = None
        self._intent_model: str = "gpt-4o-mini"
        if llm_service is not None:
            self._intent_client = getattr(llm_service, "_client", None)
            self._intent_model = getattr(llm_service, "model", "gpt-4o-mini")

    def _build_graph(self) -> Any | None:
        """Build LangGraph state graph for compile-time validation.

        The actual routing is handled imperatively in answer()/answer_stream()
        for better Langfuse span control and per-node timeout handling.
        This graph exists to verify the node topology is valid.

        Topology:
          START → classify (in _initial_state)
            ├─ place intent  → answer (skip RAG, call Places API) → END
            └─ cultural query → retrieve (RAG) → answer (LLM) → END
        """
        if StateGraph is None:
            return None

        graph = StateGraph(AgentState)
        graph.add_node("retrieve", self._retrieve_node)
        graph.add_node("answer", self._answer_node)
        graph.set_entry_point("retrieve")
        graph.add_edge("retrieve", "answer")
        graph.add_edge("answer", END)
        return graph.compile(checkpointer=MemorySaver() if MemorySaver else None)

    # -- Fairness audit logging --

    _FAIRNESS_AUDIT_DIR = Path("data/fairness_audit")

    def _fairness_audit_log(self, *, places: list, trace_id: str | None = None) -> None:
        """Log local_factor distribution for place recommendations.

        Extracts local_factor from each PlaceResult, computes distribution
        stats (count, mean, min, max, buckets), and writes a JSON line to
        data/fairness_audit/{timestamp}.jsonl.

        Wrapped in try/except — audit failure must NOT break recommendation flow.
        """
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
            min_val = min(local_factors)
            max_val = max(local_factors)

            buckets = self._bucket_local_factors(local_factors)

            audit_record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "trace_id": trace_id,
                "count": count,
                "mean": round(mean_val, 4),
                "min": round(min_val, 4),
                "max": round(max_val, 4),
                "local_factors": [round(lf, 4) for lf in local_factors],
                "distribution": buckets,
            }

            self._FAIRNESS_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            filepath = self._FAIRNESS_AUDIT_DIR / f"{ts}.jsonl"
            with open(filepath, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(audit_record, ensure_ascii=False) + "\n")

            logger.info(
                "fairness_audit.logged",
                filepath=str(filepath),
                count=count,
                mean=round(mean_val, 4),
            )
        except Exception as exc:
            logger.warning(
                "fairness_audit.error",
                reason=type(exc).__name__,
                message="audit failure must not break recommendation flow",
            )

    @staticmethod
    def _bucket_local_factors(local_factors: list[float]) -> dict[str, int]:
        """Bucket local_factor values into distribution ranges."""
        buckets: dict[str, int] = {
            "<0.1": 0,
            "0.1-0.3": 0,
            "0.3-0.5": 0,
            ">0.5": 0,
        }
        for lf in local_factors:
            if lf < 0.1:
                buckets["<0.1"] += 1
            elif lf < 0.3:
                buckets["0.1-0.3"] += 1
            elif lf < 0.5:
                buckets["0.3-0.5"] += 1
            else:
                buckets[">0.5"] += 1
        return buckets

    def _start_langfuse_span(
        self,
        *,
        trace_id: str,
        name: str,
        as_type: str = "span",
        input_data: dict | None = None,
    ) -> Any | None:
        """Create a Langfuse observation span, gracefully degrading on error.

        Returns the span object or None if Langfuse is unavailable.
        All Langfuse calls are wrapped in try/except — Langfuse down means
        silently dropped with a structlog warning only.
        """
        if self._langfuse_client is None:
            return None
        try:
            from langfuse.types import TraceContext

            span = self._langfuse_client.start_observation(
                trace_context=TraceContext(trace_id=trace_id),
                name=name,
                as_type=as_type,  # type: ignore[arg-type]
                input=input_data,
            )
            logger.info("langfuse.span_started", trace_id=trace_id, name=name)
            return span
        except Exception as exc:
            logger.warning(
                "langfuse.error",
                operation="start_observation",
                name=name,
                reason=type(exc).__name__,
            )
            return None

    def _end_langfuse_span(
        self,
        span: Any | None,
        *,
        trace_id: str,
        name: str,
        output_data: dict | None = None,
    ) -> None:
        """End a Langfuse span with output metadata, gracefully degrading."""
        if span is None:
            return
        try:
            if output_data:
                span.update(output=output_data)
            span.end()
            logger.info("langfuse.span_ended", trace_id=trace_id, name=name)
        except Exception as exc:
            logger.warning(
                "langfuse.error",
                operation="end_observation",
                name=name,
                reason=type(exc).__name__,
            )

    async def answer(self, *, session_id: str, message: str, language: str = "vi") -> ChatResponse:
        """Return a grounded ChatResponse and persist the turn for the session.

        Soft routing:
          - conversational/greeting → skip RAG, answer directly from LLM
          - everything else → retrieve RAG + answer (LLM decides what to use)
          - place/navigation intent → also call Places API alongside RAG
        """
        t0 = time.perf_counter()
        state = await self._initial_state(session_id, message, language)

        # -- Langfuse trace creation --
        trace_id: str | None = None
        if self._langfuse_client is not None:
            try:
                trace_id = self._langfuse_client.create_trace_id(seed=session_id)
                state["langfuse_trace_id"] = trace_id
                logger.info("langfuse.trace_created", trace_id=trace_id, session_id=session_id)
            except Exception as exc:
                logger.warning(
                    "langfuse.error",
                    operation="create_trace_id",
                    reason=type(exc).__name__,
                )

        intent = state.get("intent", "unknown")
        is_conversational = intent == "conversational"
        is_place = intent in {"restaurant_search", "navigation"}

        # -- Conversational: skip RAG entirely --
        if is_conversational:
            state["chunks"] = []
            state["citations"] = []
            logger.info("agent.skip_retrieval", session_id=session_id, intent=intent, reason="conversational")
        else:
            # -- Retrieve RAG (always for non-conversational) --
            retrieve_span = self._start_langfuse_span(
                trace_id=trace_id or "",
                name="retrieve",
                as_type="retriever",
                input_data={"query": state["retrieval_query"]},
            )
            try:
                state = await asyncio.wait_for(
                    self._retrieve_node(state), timeout=NODE_TIMEOUT_RETRIEVE
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "agent.node_timeout",
                    session_id=session_id,
                    node="retrieve",
                    timeout_seconds=NODE_TIMEOUT_RETRIEVE,
                )
                state["fallback_reason"] = f"NodeTimeoutError(retrieve, {NODE_TIMEOUT_RETRIEVE}s)"
                state["chunks"] = []
                state["citations"] = []
            self._end_langfuse_span(
                retrieve_span,
                trace_id=trace_id or "",
                name="retrieve",
                output_data={
                    "mode": "hybrid" if self._hybrid_retriever else "keyword" if self._retriever else "none",
                    "retrieval_count": len(state.get("chunks", [])),
                },
            )

        # -- Answer: LLM decides how to use context + Places API --
        answer_span = self._start_langfuse_span(
            trace_id=trace_id or "",
            name="answer",
            input_data={
                "chunks_count": len(state.get("chunks", [])),
                "intent": intent,
            },
        )
        try:
            state = await asyncio.wait_for(
                self._answer_node(state), timeout=NODE_TIMEOUT_ANSWER
            )
        except asyncio.TimeoutError:
            logger.warning(
                "agent.node_timeout",
                session_id=session_id,
                node="answer",
                timeout_seconds=NODE_TIMEOUT_ANSWER,
            )
            state["fallback_reason"] = state.get("fallback_reason") or f"NodeTimeoutError(answer, {NODE_TIMEOUT_ANSWER}s)"
            state["response"] = await self._compose_fallback(state, state.get("fallback_reason", "llm_timeout"))
        response = state["response"]
        self._end_langfuse_span(
            answer_span,
            trace_id=trace_id or "",
            name="answer",
            output_data={
                "response_length": len(response.message),
                "fallback": response.fallback,
                "citation_count": len(response.citations),
            },
        )

        await self._save_turn(session_id, message, response.message)

        if trace_id is not None:
            response.langfuse_trace_id = trace_id

        logger.info(
            "agent.graph_end",
            session_id=session_id,
            intent=intent,
            retrieval_count=len(response.citations),
            fallback=response.fallback,
            fallback_reason=state.get("fallback_reason"),
            latency_ms=round((time.perf_counter() - t0) * 1000, 3),
            langfuse_trace_id=trace_id,
        )
        return response

    async def answer_stream(
        self, *, session_id: str, message: str, language: str = "vi"
    ) -> AsyncGenerator[str, None]:
        """Yield answer tokens, then a citations marker and DONE marker.

        Soft routing:
          - conversational/greeting → skip RAG, answer directly
          - everything else → retrieve RAG + LLM stream
          - place/navigation → enrich with Places API alongside RAG
        """
        state = await self._initial_state(session_id, message, language)

        # -- Langfuse trace creation --
        trace_id: str | None = None
        if self._langfuse_client is not None:
            try:
                trace_id = self._langfuse_client.create_trace_id(seed=session_id)
                state["langfuse_trace_id"] = trace_id
                logger.info("langfuse.trace_created", trace_id=trace_id, session_id=session_id)
            except Exception as exc:
                logger.warning(
                    "langfuse.error",
                    operation="create_trace_id",
                    reason=type(exc).__name__,
                )

        # -- Classify intent --
        intent = state.get("intent", "unknown")
        is_conversational = intent == "conversational"

        # -- Conversational: skip RAG --
        if is_conversational:
            state["chunks"] = []
            state["citations"] = []
            fallback_reason: str | None = None
            logger.info("agent.skip_retrieval", session_id=session_id, intent=intent, reason="conversational")
        else:
            retrieve_span = self._start_langfuse_span(
                trace_id=trace_id or "",
                name="retrieve",
                as_type="retriever",
                input_data={"query": state["retrieval_query"]},
            )
            try:
                state = await asyncio.wait_for(
                    self._retrieve_node(state), timeout=NODE_TIMEOUT_RETRIEVE
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "agent.node_timeout",
                    session_id=session_id,
                    node="retrieve",
                    timeout_seconds=NODE_TIMEOUT_RETRIEVE,
                )
                fallback_reason = f"NodeTimeoutError(retrieve, {NODE_TIMEOUT_RETRIEVE}s)"
                state["chunks"] = []
                state["citations"] = []
            else:
                fallback_reason = None
            self._end_langfuse_span(
                retrieve_span,
                trace_id=trace_id or "",
                name="retrieve",
                output_data={
                    "mode": "hybrid" if self._hybrid_retriever else "keyword" if self._retriever else "none",
                    "retrieval_count": len(state.get("chunks", [])),
                },
            )

        answer_text = ""
        citations = state.get("citations", [])
        fallback_reason: str | None = None

        logger.info(
            "agent.stream_start",
            session_id=session_id,
            checkpoint_mode=self.checkpoint_mode,
            retrieval_count=len(citations),
            intent=intent,
        )

        # -- Place intent: use Places API (stream the result text) --
        if intent in {"restaurant_search", "navigation"} and self._place_recommendation_service is not None:
            try:
                place_response = await self._place_recommendation_service.recommend(
                    query=state["message"],
                    language=language,
                    session_id=session_id,
                )
                answer_text = place_response.message
                citations = place_response.citations
                yield answer_text
                logger.info(
                    "agent.stream_place_recommendation",
                    session_id=session_id,
                    result_count=len(place_response.places),
                    fallback=place_response.fallback,
                )
            except Exception as exc:
                fallback_reason = type(exc).__name__
                logger.warning(
                    "agent.place_recommendation_stream_failed",
                    session_id=session_id,
                    reason=fallback_reason,
                )

        # -- Default: LLM streaming --
        if not answer_text and self._llm_service is not None:
            answer_span = self._start_langfuse_span(
                trace_id=trace_id or "",
                name="answer",
                input_data={"chunks_count": len(state.get("chunks", []))},
            )
            try:
                stream = self._llm_service.answer_stream(
                    chunks=state.get("chunks", []),
                    citations=citations,
                    query=state["retrieval_query"],
                    language=language,
                    session_id=session_id,
                )
                while True:
                    try:
                        token = await asyncio.wait_for(
                            stream.__anext__(), timeout=NODE_TIMEOUT_ANSWER
                        )
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        logger.warning(
                            "agent.node_timeout",
                            session_id=session_id,
                            node="answer_stream",
                            timeout_seconds=NODE_TIMEOUT_ANSWER,
                        )
                        fallback_reason = f"NodeTimeoutError(answer_stream, {NODE_TIMEOUT_ANSWER}s)"
                        break
                    answer_text += token
                    yield token
            except Exception as exc:
                fallback_reason = type(exc).__name__
                logger.warning("agent.answer_fallback", session_id=session_id, fallback_reason=fallback_reason)
            self._end_langfuse_span(
                answer_span,
                trace_id=trace_id or "",
                name="answer",
                output_data={
                    "response_length": len(answer_text),
                    "fallback": fallback_reason is not None,
                },
            )

        if not answer_text:
            response = await self._compose_fallback(state, fallback_reason or "llm_unavailable")
            answer_text = response.message
            citations = response.citations
            yield answer_text

        await self._save_turn(session_id, message, answer_text)
        yield f"[CITATIONS] {json.dumps([c.model_dump() for c in citations], ensure_ascii=False)}"
        yield "[DONE]"
        logger.info(
            "agent.stream_complete",
            session_id=session_id,
            fallback_reason=fallback_reason,
            langfuse_trace_id=trace_id,
        )


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

        # LLM-based intent classification (with keyword fallback)
        # Uses a lightweight gpt-4o-mini call with 3s timeout — understands semantics, not keywords
        intent, confidence = await classify_intent(
            message, client=self._intent_client, model=self._intent_model
        )
        logger.info(
            "agent.intent_classified",
            session_id=session_id,
            intent=intent,
            confidence=confidence,
            method="llm" if confidence > 0.5 else "keyword_fallback",
        )

        return {
            "session_id": session_id,
            "message": message,
            "language": language,
            "history": history,
            "retrieval_query": retrieval_query,
            "fallback_reason": None,
            "intent": intent,
        }

    async def _retrieve_node(self, state: AgentState) -> AgentState:
        query = state["retrieval_query"]

        # -- Semantic cache check (optional, graceful degradation) --
        cache_hit_response: str | None = None
        if self._semantic_cache is not None and self._embedding_service is not None:
            try:
                query_embedding = await self._embedding_service.embed_texts([query])
                if query_embedding and len(query_embedding) > 0:
                    embedding = query_embedding[0]
                    cache_hit_response = await self._semantic_cache.lookup(
                        query, embedding
                    )
            except Exception as exc:
                # Cache failure must NOT break retrieval
                logger.warning(
                    "agent.semantic_cache_lookup_failed",
                    session_id=state["session_id"],
                    reason=type(exc).__name__,
                )

        if cache_hit_response is not None:
            # Cache hit — use cached response text directly
            state["citations"] = []
            # Build a synthetic chunk from cached response for downstream use
            from app.models.rag import RAGChunk
            state["chunks"] = [RAGChunk(
                chunk_id="cache_hit",
                source_id="semantic_cache",
                title="Semantic Cache Hit",
                url="",
                domain="cache",
                source_type="cache",
                reliability="low",
                language="unknown",
                location="",
                text=cache_hit_response,
                chunk_index=0,
                total_chunks=1,
            )]
            logger.info(
                "agent.cache_hit",
                session_id=state["session_id"],
            )
            return state

        # -- Normal retrieval path --
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

        # -- Store in semantic cache on miss (best-effort) --
        if self._semantic_cache is not None and self._embedding_service is not None and result.chunks:
            try:
                response_text = " ".join(c.text for c in result.chunks)
                query_embedding = await self._embedding_service.embed_texts([query])
                if query_embedding and len(query_embedding) > 0:
                    await self._semantic_cache.store(
                        query, query_embedding[0], response_text
                    )
            except Exception as exc:
                # Cache store failure must NOT break retrieval
                logger.warning(
                    "agent.semantic_cache_store_failed",
                    session_id=state["session_id"],
                    reason=type(exc).__name__,
                )

        logger.info(
            "agent.node_complete",
            phase="retrieve",
            session_id=state["session_id"],
            retrieval_mode=mode,
            retrieval_count=len(result.chunks),
        )
        return state

    async def _answer_node(self, state: AgentState) -> AgentState:
        """Answer using LLM. Places intent gets enriched with Places API data.

        Soft approach: LLM always answers, Places data is optional enrichment.
        No hard routing — LLM decides how to combine context + places.
        """
        intent = state.get("intent") or detect_intent(state["message"])
        is_place = intent in {"restaurant_search", "navigation"}

        # For place/navigation: try Places API for enrichment
        if is_place and self._place_recommendation_service is not None:
            try:
                place_response = await self._place_recommendation_service.recommend(
                    query=state["message"],
                    language=state["language"],
                    session_id=state["session_id"],
                )
                self._fairness_audit_log(
                    places=place_response.places,
                    trace_id=state.get("langfuse_trace_id"),
                )

                # Build enriched context: RAG chunks + Places data
                # Prepend places info as additional context for the LLM
                if place_response.places:
                    places_context = self._build_places_context(place_response.places)
                    # Append places context to existing chunks
                    from app.models.rag import RAGChunk
                    place_chunk = RAGChunk(
                        chunk_id="places_api",
                        source_id="places_api",
                        title="Local Places (Google Places API)",
                        url="",
                        domain="places",
                        source_type="api",
                        reliability="high",
                        language="unknown",
                        location="",
                        text=places_context,
                        chunk_index=0,
                        total_chunks=1,
                    )
                    state["chunks"] = [place_chunk] + state.get("chunks", [])
                    state["citations"] = place_response.citations + state.get("citations", [])

                # Build answer from enriched context
                response = ChatResponse(
                    session_id=state["session_id"],
                    message=place_response.message,
                    citations=state["citations"],
                    places=place_response.places,
                    reasoning_log=place_response.reasoning_log,
                    intent=PLACE_RECOMMENDATION_INTENT,
                    langfuse_trace_id=state.get("langfuse_trace_id"),
                    latency_ms=place_response.latency_ms,
                    fallback=place_response.fallback,
                )

                # Cultural context enrichment (SOC-05)
                cultural_chunks = self._extract_cultural_context(state.get("chunks", []))
                if cultural_chunks:
                    cultural_intro = self._build_cultural_intro(
                        cultural_chunks, state["language"]
                    )
                    response.message = f"{cultural_intro}\n\n{response.message}"

                state["response"] = response
                logger.info(
                    "agent.node_complete",
                    phase="place_recommendation",
                    session_id=state["session_id"],
                    intent=intent,
                    result_count=len(response.places),
                    fallback=response.fallback,
                )
                return state
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "agent.place_recommendation_fallback",
                    session_id=state["session_id"],
                    reason=type(exc).__name__,
                )
                # Fall through to LLM answer

        # Default: LLM answers with RAG context
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

    def _build_places_context(self, places: list) -> str:
        """Build a text context block from Places API results for LLM injection."""
        lines = ["Các địa điểm tìm được từ Google Places:"]
        for i, place in enumerate(places[:5], 1):
            name = getattr(place, "display_name", "Unknown")
            address = getattr(place, "formatted_address", "")
            rating = getattr(place, "rating", None)
            rating_str = f" (đánh giá {rating})" if rating else ""
            lines.append(f"{i}. **{name}**{rating_str} — {address}")
        return "\n".join(lines)

    # -- SOC-05: Cultural context before commercial recommendations --

    _CULTURAL_DOMAINS = {"culture", "history", "heritage", "tradition", "festival", "temple", "đình", "chùa", "di tích", "lễ hội", "văn hóa"}

    def _extract_cultural_context(self, chunks: list[RAGChunk]) -> list[RAGChunk]:
        """Extract chunks related to cultural/historical content from retrieval results.

        Returns chunks whose domain or source_type indicates cultural/historical relevance.
        Limited to top 3 to keep the intro concise.
        """
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

    def _build_cultural_intro(
        self, cultural_chunks: list[RAGChunk], language: str
    ) -> str:
        """Build a brief cultural context intro from retrieved chunks."""
        if language == "vi":
            intro = "🏛️ **Về Hàm Ninh — Bối cảnh văn hóa:**"
        else:
            intro = "🏛️ **About Hàm Ninh — Cultural Context:**"

        snippets = []
        for chunk in cultural_chunks[:2]:  # Max 2 snippets for brevity
            # Truncate to first 150 chars
            text = (chunk.text or "")[:150]
            if text:
                snippets.append(f"- {text}")

        if snippets:
            return f"{intro}\n" + "\n".join(snippets)
        return intro

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
            response = await self._place_recommendation_service.recommend(
                query=state["message"],
                language=state["language"],
                session_id=state["session_id"],
            )
            # Log fairness audit for place recommendations (best-effort, never breaks flow)
            self._fairness_audit_log(
                places=response.places,
                trace_id=state.get("langfuse_trace_id"),
            )

            # -- SOC-05: Cultural context before commercial recommendations --
            # If we have cultural/historical chunks, prepend context to the response.
            cultural_chunks = self._extract_cultural_context(state.get("chunks", []))
            if cultural_chunks:
                cultural_intro = self._build_cultural_intro(
                    cultural_chunks, state["language"]
                )
                response.message = f"{cultural_intro}\n\n{response.message}"
                response.reasoning_log = (
                    f"cultural_context=true cultural_chunks={len(cultural_chunks)} "
                    f"{response.reasoning_log or ''}"
                )

            return response
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
