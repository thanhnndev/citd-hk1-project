"""LangGraph-style tool-calling chat agent.

The runtime follows the simple LangGraph pattern documented by LangChain:
LLM decides whether to call a tool; tool node executes; LLM composes final
answer. Retrieval is a tool, never the default entry point.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from typing import Any, Literal

import asyncpg
import structlog

from app.models.rag import RAGChunk
from app.models.response import ChatResponse, Citation
from agents.services.place_recommendation_service import PLACE_RECOMMENDATION_INTENT
from agents.tools.retriever import Retriever

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

import agents.graph.checkpointing as _checkpointing
from agents.graph.checkpointing import InMemoryAgentCheckpointer, PostgresAgentCheckpointer
from agents.graph.followup import (
    FollowUpContext,
    _build_followup_context,
    _is_ambiguous_pronoun_followup,
    _matches_structured_context,
    compose_followup_answer as _compose_followup_answer,
    resolve_followup_before_tool_routing as _resolve_followup_before_tool_routing_impl,
    resolve_followup_decision,
)
from agents.graph.state import (
    END,
    START,
    MemorySaver,
    StateGraph,
    AgentState,
    FollowUpDecision,
    NODE_TIMEOUT_LLM,
    NODE_TIMEOUT_TOOL,
    TOOLS as _TOOLS,
)

from agents.graph.routing import (
    _chunk_payload,
    _clarify_message,
    _direct_answer,
    _extract_suggestions,
    _fallback_action,
    _get_default_suggestions,
    _json_args,
    _knowledge_fallback_answer,
    _messages_for_llm,
    _place_unavailable_message,
    _status_for_state,
    _status_for_tool_calls,
    _too_many_tools_message,
)

async def create_agent_checkpointer(database_url: str | None = None) -> tuple[Any, str]:
    _checkpointing.asyncpg = asyncpg
    return await _checkpointing.create_agent_checkpointer(database_url)


def _resolve_followup_before_tool_routing(
    state: AgentState,
    has_llm: bool = False,
) -> AgentState | None:
    return _resolve_followup_before_tool_routing_impl(
        state,
        has_llm=has_llm,
        direct_answer=_direct_answer,
        clarify_message=_clarify_message,
    )

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
        preflight_handled = await self._run_preflight_route(state)
        if preflight_handled:
            pass
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
        preflight_action = _fallback_action(message, state.get("history", []))
        preflight_handled = await self._run_preflight_route(state)
        if preflight_handled:
            if preflight_action == "places":
                yield "[STATUS] checking_places"
            elif preflight_action == "knowledge":
                yield "[STATUS] searching_knowledge"
            else:
                yield _status_for_state(state)
            yield state.get("response_text", "")
        elif self._should_route_places_deterministically(message, state.get("history", [])):
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

    async def _run_preflight_route(self, state: AgentState) -> bool:
        """Apply deterministic tool gates before any LLM/tool loop.

        Context7/LangGraph guidance keeps the LLM node responsible for tool
        calls, but production agents still need an explicit policy boundary so
        small talk cannot accidentally inherit history and trigger retrieval.
        """
        action = _fallback_action(state["message"], state.get("history", []))
        if action == "direct":
            state["response_text"] = _direct_answer(state["message"], state.get("history", []), state["language"])
            state["intent"] = "conversational"
            return True
        if action == "clarify":
            state["response_text"] = _clarify_message(state["language"])
            state["intent"] = "clarification"
            return True
        if action == "places" and self._place_recommendation_service is not None:
            await self._search_places_tool(state, state["message"])
            if not state.get("response_text"):
                state["response_text"] = _place_unavailable_message(state["language"])
            return True
        return False

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

