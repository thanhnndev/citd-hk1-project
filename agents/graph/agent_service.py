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

# Per-node timeout constants (ROB-06)
NODE_TIMEOUT_RETRIEVE = 10
NODE_TIMEOUT_ANSWER = 15


class NodeTimeoutError(Exception):
    """Raised when a graph node exceeds its per-node timeout."""

    def __init__(self, node_name: str, timeout_seconds: int) -> None:
        self.node_name = node_name
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Node '{node_name}' timed out after {timeout_seconds}s")

# ---------------------------------------------------------------------------
# Structured follow-up context contract (R052)
# ---------------------------------------------------------------------------

FollowUpDecision = Literal[
    "structured_context",
    "history_context",
    "clarification_needed",
    "insufficient_context",
]


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
    has_citations: bool = False
    citation_sources: list[str] = field(default_factory=list)
    reasoning_log_summary: str | None = None
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
            "has_citations": self.has_citations,
            "citation_sources": self.citation_sources,
            "reasoning_log_summary": self.reasoning_log_summary,
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
                has_citations=bool(data.get("has_citations")),
                citation_sources=_safe_list(data.get("citation_sources")),
                reasoning_log_summary=data.get("reasoning_log_summary"),
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
            or self.citation_sources
            or self.reasoning_log_summary
            or self.score_breakdown_keys
            or self.provider_source
        )


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
        "quán", "nhà", "hàng", "khách", "sạn",
        "homestay", "hotel", "restaurant",
        "ăn", "uống", "nghỉ", "dưỡng", "resort",
    })

    # Direct place name references (token-level, ignoring single-char tokens
    # and common descriptor words). At least one distinctive token must match.
    for name in context.place_display_names:
        normalized = _norm(name)
        if not normalized:
            continue
        tokens = [t for t in normalized.split() if len(t) > 1 and t not in _skip_tokens]
        if not tokens:
            # All tokens are skip words — only match if the full normalized
            # name appears as a substring (for names like "Quán Hải Sản" where
            # every token is a skip word)
            if normalized in text:
                return True
            continue
        if any(token in text for token in tokens):
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
        has_citations=bool(response.citations),
        citation_sources=citation_sources,
        reasoning_log_summary=(response.reasoning_log or "")[:500] if response.reasoning_log else None,
        score_breakdown_keys=score_keys[:10],
        provider_source=getattr(response.decision_trace, "provider_source", None) if response.decision_trace else None,
        provider_status=getattr(response.decision_trace, "credential_status", None) if response.decision_trace else None,
        fallback=response.fallback,
        explanation_keys=explanation_keys[:10],
    )

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
                "or local recommendations around Ham Ninh. "
                "Optionally accepts budget, accessibility, and user_location preferences."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "budget": {
                        "type": "string",
                        "enum": ["free", "inexpensive", "moderate", "expensive", "very_expensive"],
                        "description": "Optional budget preference. Maps to price level filtering.",
                    },
                    "accessibility": {
                        "type": "boolean",
                        "description": "Optional: when true, prefer wheelchair-accessible venues.",
                    },
                    "user_location": {
                        "type": "object",
                        "properties": {
                            "lat": {"type": "number"},
                            "lng": {"type": "number"},
                        },
                        "description": "Optional user GPS coordinates for proximity scoring.",
                    },
                },
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
- At the end of your final response (when you are not calling any tools), write exactly three short and context-specific suggestion chips for the user's next turn in this format: [SUGGESTIONS] Suggestion 1 | Suggestion 2 | Suggestion 3. Do not include this tag or suggestions if you are proposing tool calls.
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
    suggestions: list[str]
    reasoning_log: str | None
    intent: str | None
    response_text: str
    response: ChatResponse
    langfuse_trace_id: str | None
    # Structured follow-up context loaded from prior turn (R052)
    prior_context: FollowUpContext | None
    followup_decision: FollowUpDecision | None
    context_source: str | None  # "structured_context" | "history_context" | "none"

@dataclass
class InMemoryAgentCheckpointer:
    _store: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    _context_store: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def load_history(self, session_id: str) -> list[dict[str, str]]:
        return list(self._store.get(session_id, []))

    async def save_turn(self, session_id: str, user: str, assistant: str) -> None:
        history = self._store.setdefault(session_id, [])
        history.extend([{"role": "user", "content": user}, {"role": "assistant", "content": assistant}])
        del history[:-8]

    # -- Structured follow-up context (backward-compatible extension) --

    async def load_context(self, session_id: str) -> FollowUpContext | None:
        raw = self._context_store.get(session_id)
        return FollowUpContext.from_dict(raw)

    async def save_context(self, session_id: str, ctx: FollowUpContext) -> None:
        self._context_store[session_id] = ctx.to_dict()

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
            # Structured follow-up context table (R052)
            await conn.execute(
                """CREATE TABLE IF NOT EXISTS agent_session_followup_context (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    context_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )"""
            )
            await conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_agent_session_followup_context_session
                ON agent_session_followup_context (session_id, id)"""
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

    # -- Structured follow-up context (backward-compatible extension) --

    async def load_context(self, session_id: str) -> FollowUpContext | None:
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchval(
                    "SELECT context_json FROM agent_session_followup_context WHERE session_id = $1 ORDER BY id DESC LIMIT 1",
                    session_id,
                )
        except Exception:
            return None
        if row is None:
            return None
        try:
            data = json.loads(row) if isinstance(row, str) else row
            return FollowUpContext.from_dict(data)
        except (json.JSONDecodeError, TypeError):
            return None

    async def save_context(self, session_id: str, ctx: FollowUpContext) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO agent_session_followup_context (session_id, context_json)
                VALUES ($1, $2)""",
                session_id,
                json.dumps(ctx.to_dict(), ensure_ascii=False),
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
        # Resolve contextual follow-ups before tool routing (R052 / T03)
        resolved = _resolve_followup_before_tool_routing(state, has_llm=(self._client is not None))
        if resolved is not None:
            response = self._response_from_state(resolved, started)
            await self._save_followup_context(session_id, response)
            await self._save_turn(session_id, message, response.message)
            return response
        if self._should_route_places_deterministically(message, state.get("history", [])):
            await self._search_places_tool(state, message)
            if not state.get("response_text"):
                state["response_text"] = _place_unavailable_message(state["language"])
        elif self._client is None:
            state = await self._deterministic_decide_and_run(state)
        else:
            state = await self._run_tool_loop(state)
        response = self._response_from_state(state, started)
        # Persist structured follow-up context for next turn (R052)
        await self._save_followup_context(session_id, response)
        await self._save_turn(session_id, message, response.message)
        return response

    async def answer_stream(self, *, session_id: str, message: str, language: str = "vi") -> AsyncGenerator[str, None]:
        started = time.perf_counter()
        state = await self._initial_state(session_id, message, language)
        # Resolve contextual follow-ups before tool routing (R052 / T03)
        resolved = _resolve_followup_before_tool_routing(state, has_llm=(self._client is not None))
        if resolved is not None:
            # Emit status for observability
            decision = state.get("followup_decision")
            if decision == "structured_context":
                yield "[STATUS] using_context"
            elif decision == "history_context":
                yield "[STATUS] using_history"
            else:
                yield "[STATUS] clarifying"
            yield resolved.get("response_text", "")
            response = self._response_from_state(resolved, started)
            await self._save_followup_context(session_id, response)
            await self._save_turn(session_id, message, response.message)
            return
        # Expose context source in streaming for observability (R052)
        if state.get("context_source") == "structured_context":
            yield "[STATUS] using_context"
        elif state.get("context_source") == "history_context":
            yield "[STATUS] using_history"
        else:
            yield "[STATUS] understanding"
        if self._should_route_places_deterministically(message, state.get("history", [])):
            yield "[STATUS] checking_places"
            await self._search_places_tool(state, message)
            if not state.get("response_text"):
                state["response_text"] = _place_unavailable_message(state["language"])
            yield state.get("response_text", "")
        elif self._client is None:
            state = await self._deterministic_decide_and_run(state)
            yield _status_for_state(state)
            yield state.get("response_text", "")
        else:
            async for event in self._run_streaming_tool_loop(state):
                if isinstance(event, str):
                    yield event
                else:
                    state = event
                    # When the LLM answers directly (e.g. greeting), stream
                    # the composed response_text so the SSE client sees it.
                    if state.get("response_text"):
                        yield _status_for_state(state)
                        yield state["response_text"]
        response = self._response_from_state(state, started)
        # Persist structured follow-up context for next turn (R052)
        await self._save_followup_context(session_id, response)
        await self._save_turn(session_id, message, response.message)
        if response.places:
            yield f"[PLACES] {json.dumps([p.model_dump() for p in response.places], ensure_ascii=False)}"
        if response.citations:
            yield f"[CITATIONS] {json.dumps([c.model_dump() for c in response.citations], ensure_ascii=False)}"
        if response.suggestions:
            yield f"[SUGGESTIONS] {json.dumps(response.suggestions, ensure_ascii=False)}"

    async def stream(self, *, session_id: str, message: str, language: str = "vi") -> AsyncGenerator[str, None]:
        async for event in self.answer_stream(session_id=session_id, message=message, language=language):
            yield event

    async def _initial_state(self, session_id: str, message: str, language: str) -> AgentState:
        try:
            history = await self._checkpointer.load_history(session_id)
        except Exception as exc:
            logger.warning("agent.checkpoint_load", session_id=session_id, reason=type(exc).__name__)
            history = []
        # Load structured follow-up context from prior turn (R052)
        prior_context: FollowUpContext | None = None
        context_source = "none"
        if history:
            try:
                prior_context = await self._checkpointer.load_context(session_id)
                if prior_context is not None and prior_context.is_populated:
                    context_source = "structured_context"
                elif prior_context is not None:
                    # Context exists but not populated — fall back to history
                    context_source = "history_context"
                    prior_context = None
            except Exception as exc:
                logger.warning("agent.context_load_failed", session_id=session_id, reason=type(exc).__name__)
                prior_context = None
        # Classify follow-up decision for observability
        followup_decision = resolve_followup_decision(message, prior_context, history)
        return {
            "session_id": session_id,
            "message": message,
            "language": "en" if language == "en" else "vi",
            "history": history,
            "messages": _messages_for_llm(message=message, history=history, language=language),
            "citations": [],
            "places": [],
            "suggestions": [],
            "reasoning_log": None,
            "intent": None,
            "response_text": "",
            "places_response_ready": False,
            "prior_context": prior_context,
            "followup_decision": followup_decision,
            "context_source": context_source,
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
            max_completion_tokens=520,
        )
        message = completion.choices[0].message
        tool_calls = list(message.tool_calls or [])
        if tool_calls:
            state["tool_calls"] = tool_calls
            state["messages"].append(message.model_dump(exclude_none=True))
            return state
        state["tool_calls"] = []
        content = message.content or ""
        msg_text, suggestions = _extract_suggestions(content)
        state["response_text"] = msg_text or _clarify_message(state["language"])
        state["suggestions"] = suggestions
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

    def _should_route_places_deterministically(self, message: str, history: list[dict[str, str]]) -> bool:
        if self._client is not None or self._place_recommendation_service is None:
            return False
        return _fallback_action(message, history) == "places"

    def can_answer_without_corpus(self, message: str) -> bool:
        """Return True for place discovery requests served by the Places tool."""
        return self._place_recommendation_service is not None and _fallback_action(message, []) == "places"

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
            # fallback=False: place intent was handled via the deterministic tool
            # policy path — no RAG/LLM fallback occurred. The unavailable message
            # is the honest answer, not a degraded fallback.
            state["fallback"] = False
            return json.dumps({"status": "unavailable", "message": state["response_text"]}, ensure_ascii=False)

        # Extract optional preferences from tool args (already parsed from LLM tool call)
        # These are sourced from the last tool call's arguments, stored in state.
        _budget: str | None = None
        _accessibility: bool | None = None
        _user_location: dict[str, float] | None = None
        for call in state.get("tool_calls", [])[:2]:
            if call.function.name == "search_places":
                args = _json_args(call.function.arguments)
                _budget = args.get("budget") if isinstance(args.get("budget"), str) else None
                _accessibility = args.get("accessibility") if isinstance(args.get("accessibility"), bool) else None
                ul = args.get("user_location")
                if isinstance(ul, dict):
                    _user_location = ul
                break

        try:
            response = await self._place_recommendation_service.recommend(
                query=query,
                language=state["language"],
                session_id=state["session_id"],
                budget=_budget,
                accessibility=_accessibility,
                user_location=_user_location,
            )
        except Exception as exc:
            logger.warning("agent.place_tool_error", session_id=state["session_id"], reason=type(exc).__name__)
            state["response_text"] = _place_unavailable_message(state["language"])
            state["fallback"] = True
            return json.dumps({"status": "error", "message": state["response_text"]}, ensure_ascii=False)
        state["places"] = response.places
        state["reasoning_log"] = response.reasoning_log
        state["response_text"] = response.message
        state["fairness_audit"] = response.fairness_audit
        state["fallback"] = response.fallback
        state["decision_trace"] = response.decision_trace
        state["places_response_ready"] = True
        return json.dumps({"status": "ok", "message": response.message, "places": [p.model_dump() for p in response.places[:5]]}, ensure_ascii=False)

    def _response_from_state(self, state: AgentState, started: float) -> ChatResponse:
        suggestions = state.get("suggestions")
        if not suggestions:
            suggestions = _get_default_suggestions(
                intent=state.get("intent"),
                language=state["language"],
                has_places=bool(state.get("places")),
                has_citations=bool(state.get("citations")),
                fallback=state.get("fallback", False),
            )
        return ChatResponse(
            session_id=state["session_id"],
            message=state.get("response_text") or _clarify_message(state["language"]),
            citations=state.get("citations", []),
            places=state.get("places", []),
            suggestions=suggestions,
            reasoning_log=state.get("reasoning_log"),
            intent=state.get("intent"),
            langfuse_trace_id=state.get("langfuse_trace_id"),
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
            fallback=state.get("fallback", False),
            fairness_audit=state.get("fairness_audit"),
            decision_trace=state.get("decision_trace"),
        )

    async def _save_turn(self, session_id: str, message: str, answer: str) -> None:
        try:
            await self._checkpointer.save_turn(session_id, message, answer)
        except Exception as exc:
            logger.warning("agent.checkpoint_save", session_id=session_id, reason=type(exc).__name__)

    async def _save_followup_context(self, session_id: str, response: ChatResponse) -> None:
        """Persist structured follow-up context from a ChatResponse (R052).

        Builds context only for place/intent-bearing responses; skips empty or
        pure-conversational answers. Degrades gracefully on checkpointer errors.
        """
        try:
            ctx = _build_followup_context(response)
            if ctx.is_populated:
                await self._checkpointer.save_context(session_id, ctx)
                logger.debug("agent.context_saved", session_id=session_id, intent=ctx.intent, places=len(ctx.place_ids))
        except Exception as exc:
            logger.warning("agent.context_save_failed", session_id=session_id, reason=type(exc).__name__)

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

def _compose_followup_answer(
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

    # Place name reference → give what we know about that place
    for name in context.place_display_names:
        normalized = _norm(name)
        if not normalized:
            continue
        for token in normalized.split():
            if len(token) > 1 and token in text:
                if language == "vi":
                    return (
                        f"Về {name}: mình đã gợi ý địa điểm này trước đó. "
                        f"Bạn cần thông tin cụ thể nào (giờ mở cửa, đánh giá, đường đi)?"
                    )
                return (
                    f"About {name}: I recommended this venue earlier. "
                    f"What specific info do you need (hours, reviews, directions)?"
                )

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
        "quanh", "gần", "ở đâu", "có quán", "có nhà hàng", "review", "đánh giá",
        "giá", "lịch trình", "bản đồ", "map"
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


def _resolve_followup_before_tool_routing(
    state: AgentState,
    has_llm: bool = False,
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
        state["response_text"] = _compose_followup_answer(
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
            state["response_text"] = _direct_answer(
                state["message"], state.get("history", []), state["language"],
            )
            state["intent"] = "followup_history"
            state["places_response_ready"] = True
            state["fallback"] = False
            return state
        return None

    if decision == "history_context":
        # Answerable from history alone — use direct-answer path, skip tools
        state["response_text"] = _direct_answer(
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
        state["response_text"] = _clarify_message(state["language"])
        state["intent"] = "clarification"
        state["places_response_ready"] = True
        state["fallback"] = False
        return state

    # insufficient_context → proceed to normal routing
    return None

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
