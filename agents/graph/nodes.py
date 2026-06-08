"""Node functions for the HamNinhGraph LangGraph StateGraph (v4.2.0).

Provides 9 node functions (8 real + 1 stub) that form the
graph topology.  Each node is an ``async def`` that accepts an ``AgentState``
dict and returns a partial state-update dict — the standard LangGraph node
contract.

Real nodes:
    - input_guardrails_node  — prompt injection + topic gate
    - intent_router_node     — LLM structured-output intent classification
    - supervisor_node        — confidence-ladder routing decision
    - conversational_node    — direct / clarification / LLM conversational
    - output_guardrails_node — grounding verification
    - rag_agent_node         — hybrid retrieval + Cohere rerank + LLM answer
    - grade_documents_node   — LLM structured-output relevance grading
    - maps_agent_node        — PlaceRecommendationService with fairness ranking

Stub nodes (passthrough, wired for expansion):
    - rewrite_query_stub_node

Dependency injection
--------------------
LLM-dependent nodes (intent_router, conversational) read from a module-level
``NodeServices`` singleton via ``get_services()``.  The graph assembler (T02)
calls ``configure_services(services)`` before compiling the graph.  When no
services are configured, nodes degrade gracefully to heuristic paths.

Emits structured log events:
    - ``graph.node_enter`` — node execution started
    - ``graph.node_exit``  — node execution completed (with duration_ms)
    - ``graph.node_error`` — node raised an unexpected exception
"""

from __future__ import annotations

import hashlib
import inspect
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from agents.graph.state import (
    AgentState,
    GradeDocuments,
    RewriteQuery,
    RouterOutput,
    NODE_TIMEOUT_GUARDRAILS,
    NODE_TIMEOUT_INTENT_ROUTER,
)
from agents.guardrails.input_guardrails import block_injection, reject_off_topic
from agents.guardrails.output_guardrails import verify_grounding
from agents.graph.routing import (
    _clarify_message,
    _direct_answer,
    _extract_suggestions,
    _fallback_action,
    _get_default_suggestions,
    _messages_for_llm,
)
from agents.tools.retriever import citation_from_chunk

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# NodeServices — dependency injection container
# ---------------------------------------------------------------------------


@dataclass
class NodeServices:
    """Container for injected dependencies used by LLM-dependent nodes.

    The graph assembler (T02) constructs a ``NodeServices`` instance with
    the real OpenAI client, retriever, and places service, then calls
    ``configure_services(services)`` before compiling the graph.
    """

    llm_client: Any = None  # openai.AsyncOpenAI or None
    model: str = "gpt-4o-mini"
    retriever: Any = None  # Retriever or HybridRetriever or None
    places_service: Any = None  # PlaceRecommendationService or None
    cohere_reranker: Any = None  # CohereReranker or None (graceful degradation)
    llm_answer_service: Any = None  # LLMAnswerService or None


_default_services = NodeServices()


def configure_services(services: NodeServices) -> None:
    """Set the module-level NodeServices singleton.

    Called by the graph assembler (T02) before compiling the StateGraph.
    """
    global _default_services
    _default_services = services


def get_services() -> NodeServices:
    """Return the current module-level NodeServices singleton."""
    return _default_services


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_query(message: str) -> str:
    """Return a short SHA-256 hex digest (no raw text in logs)."""
    return hashlib.sha256(message.encode("utf-8")).hexdigest()[:16]


def _routing_tier_from_confidence(confidence: float) -> str:
    """Map a confidence float to a routing tier label.

    ≥ 0.75  → strict  (direct to RAG or Maps agent)
    0.45–0.75 → soft  (supervisor with tool-calling)
    < 0.45  → fallback (semantic-router embedding similarity)
    """
    if confidence >= 0.75:
        return "strict"
    if confidence >= 0.45:
        return "soft"
    return "fallback"


# ---------------------------------------------------------------------------
# 1. input_guardrails_node (REAL)
# ---------------------------------------------------------------------------


async def input_guardrails_node(state: AgentState) -> dict[str, Any]:
    """Run input guardrails: prompt injection blocking + topic rejection.

    Reads:
        - ``state["message"]``
    Writes:
        - ``guardrail_flags`` — dict with ``injection`` and ``off_topic`` verdicts
        - ``response_text`` — friendly rejection message when blocked
    """
    t0 = time.perf_counter()
    message = state.get("message", "")
    query_hash = _hash_query(message)
    session_id = state.get("session_id", "")

    logger.info(
        "graph.node_enter",
        node="input_guardrails",
        session_id=session_id,
        query_hash=query_hash,
    )

    flags: dict[str, Any] = dict(state.get("guardrail_flags") or {})

    # --- Injection check ---
    injection_result = block_injection(message)
    flags["injection"] = {
        "verdict": injection_result.verdict,
        "reason": injection_result.reason,
        "severity": injection_result.severity,
    }

    if injection_result.verdict == "blocked":
        language = state.get("language", "vi")
        blocked_msg = (
            "Xin lỗi, mình không thể xử lý yêu cầu này."
            if language == "vi"
            else "Sorry, I cannot process this request."
        )
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="input_guardrails",
            session_id=session_id,
            verdict="blocked",
            reason="injection_detected",
            duration_ms=elapsed,
        )
        return {
            "guardrail_flags": flags,
            "response_text": blocked_msg,
            "intent": "blocked",
        }

    # --- Off-topic check ---
    topic_result = reject_off_topic(message)
    flags["off_topic"] = {
        "verdict": topic_result.verdict,
        "reason": topic_result.reason,
        "severity": topic_result.severity,
    }

    if topic_result.verdict == "blocked":
        language = state.get("language", "vi")
        off_topic_msg = (
            "Mình chỉ hỗ trợ thông tin du lịch Hàm Ninh. "
            "Bạn hỏi về địa điểm, đường đi, văn hóa/lịch sử hoặc gợi ý lịch trình nhé!"
            if language == "vi"
            else "I only assist with Ham Ninh tourism. "
            "Ask about places, directions, culture/history, or trip planning!"
        )
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="input_guardrails",
            session_id=session_id,
            verdict="blocked",
            reason="off_topic",
            duration_ms=elapsed,
        )
        return {
            "guardrail_flags": flags,
            "response_text": off_topic_msg,
            "intent": "off_topic",
        }

    elapsed = round((time.perf_counter() - t0) * 1000, 3)
    logger.info(
        "graph.node_exit",
        node="input_guardrails",
        session_id=session_id,
        verdict="pass",
        duration_ms=elapsed,
    )
    return {"guardrail_flags": flags}


# ---------------------------------------------------------------------------
# 2. intent_router_node (REAL)
# ---------------------------------------------------------------------------

_INTENT_ROUTER_SYSTEM_PROMPT = """\
You are an intent classifier for the Ham Ninh tourism assistant.
Classify the user's message into one of these intents:
- cultural_query: questions about culture, history, fishing life, local food background
- food_culture: specifically about food traditions, recipes, local specialties
- restaurant_search: finding restaurants, cafes, hotels, places, directions, maps
- navigation: asking for directions, routes, maps
- conversational: greetings, thanks, capability questions, simple acknowledgments
- unknown: anything that does not fit the above

Also determine:
- confidence: your confidence in the classification (0.0 to 1.0)
- is_followup: whether the message references prior conversation context
- needs_location: whether the query requires user GPS (nearby, directions)
"""


async def intent_router_node(state: AgentState) -> dict[str, Any]:
    """Classify user intent via LLM structured output or heuristic fallback.

    When the LLM client is available, calls OpenAI with
    ``response_format=RouterOutput`` for structured classification.
    Falls back to deterministic heuristic routing when unavailable.

    Reads:
        - ``state["message"]``, ``state["history"]``, ``state["language"]``
    Writes:
        - ``intent``, ``intent_confidence``, ``routing_tier``, ``needs_location``
    """
    t0 = time.perf_counter()
    message = state.get("message", "")
    history = state.get("history", [])
    language = state.get("language", "vi")
    session_id = state.get("session_id", "")
    query_hash = _hash_query(message)

    logger.info(
        "graph.node_enter",
        node="intent_router",
        session_id=session_id,
        query_hash=query_hash,
    )

    services = get_services()
    client = services.llm_client

    # --- LLM path ---
    if client is not None and RouterOutput is not None:
        try:
            messages = [
                {"role": "system", "content": _INTENT_ROUTER_SYSTEM_PROMPT},
            ]
            # Include recent history for follow-up detection
            for item in (history or [])[-4:]:
                if item.get("role") in {"user", "assistant"} and item.get("content"):
                    messages.append({"role": item["role"], "content": item["content"]})
            messages.append({"role": "user", "content": message})

            completion = await client.chat.completions.parse(
                model=services.model,
                messages=messages,
                response_format=RouterOutput,
                max_completion_tokens=128,
            )
            message = completion.choices[0].message
            if message.parsed:
                intent_label = message.parsed.intent
                confidence = float(message.parsed.confidence)
                is_followup = bool(message.parsed.is_followup)
                needs_location = bool(message.parsed.needs_location)
                routing_tier = _routing_tier_from_confidence(confidence)
            else:
                # Fallback to heuristic if model refused or parsing failed
                raise ValueError(f"LLM refused or failed to parse: {message.refusal}")

            elapsed = round((time.perf_counter() - t0) * 1000, 3)
            logger.info(
                "graph.node_exit",
                node="intent_router",
                session_id=session_id,
                intent=intent_label,
                confidence=confidence,
                routing_tier=routing_tier,
                mode="llm",
                duration_ms=elapsed,
            )
            return {
                "intent": intent_label,
                "intent_confidence": confidence,
                "routing_tier": routing_tier,
                "needs_location": needs_location,
            }

        except Exception as exc:
            logger.warning(
                "graph.node_error",
                node="intent_router",
                session_id=session_id,
                error_type=type(exc).__name__,
                error=str(exc),
                mode="llm_failed_falling_back",
            )

    # --- Heuristic fallback ---
    action = _fallback_action(message, history)
    if action == "direct":
        intent_label = "conversational"
        confidence = 0.95
    elif action == "clarify":
        intent_label = "conversational"
        confidence = 0.6
    else:
        # Simple keyword-based heuristic
        text_lower = (message or "").lower()
        if any(term in text_lower for term in (
            "văn hóa", "văn hoá", "lịch sử", "culture", "history",
            "làng chài", "fishing", "nghề biển",
        )):
            intent_label = "cultural_query"
            confidence = 0.7
        elif any(term in text_lower for term in (
            "quán", "nhà hàng", "restaurant", "hotel", "homestay",
            "cà phê", "cafe", "tìm", "find", "search", "gần", "nearby",
        )):
            intent_label = "restaurant_search"
            confidence = 0.7
        elif any(term in text_lower for term in (
            "đường", "direction", "route", "map", "bản đồ", "chỉ đường",
        )):
            intent_label = "navigation"
            confidence = 0.65
        elif any(term in text_lower for term in (
            "món ăn", "đặc sản", "ẩm thực", "food", "specialty",
        )):
            intent_label = "food_culture"
            confidence = 0.65
        else:
            intent_label = "unknown"
            confidence = 0.4

    routing_tier = _routing_tier_from_confidence(confidence)
    needs_location = any(
        term in (message or "").lower()
        for term in ("gần đây", "nearby", "gần nhất", "nearest", "directions", "chỉ đường")
    )

    elapsed = round((time.perf_counter() - t0) * 1000, 3)
    logger.info(
        "graph.node_exit",
        node="intent_router",
        session_id=session_id,
        intent=intent_label,
        confidence=confidence,
        routing_tier=routing_tier,
        mode="heuristic",
        duration_ms=elapsed,
    )
    return {
        "intent": intent_label,
        "intent_confidence": confidence,
        "routing_tier": routing_tier,
        "needs_location": needs_location,
    }


# ---------------------------------------------------------------------------
# 3. supervisor_node (REAL)
# ---------------------------------------------------------------------------


async def supervisor_node(state: AgentState) -> dict[str, Any]:
    """Decide the next graph step based on routing tier and intent.

    Acts as the confidence-ladder dispatcher:
    - If guardrails blocked → signal END (response_text already set)
    - strict tier + cultural_query/food_culture → route to rag_agent
    - strict tier + restaurant_search/navigation → route to maps_agent
    - soft tier → route to LLM tool-calling loop (rag_agent with supervisor)
    - fallback tier → route to conversational for safe handling
    - conversational intent → route to conversational node

    Reads:
        - ``intent``, ``routing_tier``, ``guardrail_flags``, ``needs_location``
    Writes:
        - ``routing_tier`` (confirmed/adjusted), ``next_node`` hint for the
          conditional edge function in the graph assembler (T02)
    """
    t0 = time.perf_counter()
    session_id = state.get("session_id", "")
    intent = state.get("intent")
    routing_tier = state.get("routing_tier", "soft")
    flags = state.get("guardrail_flags", {})

    logger.info(
        "graph.node_enter",
        node="supervisor",
        session_id=session_id,
        intent=intent,
        routing_tier=routing_tier,
    )

    # --- Guardrail-blocked short-circuit ---
    injection = flags.get("injection", {})
    off_topic = flags.get("off_topic", {})
    if injection.get("verdict") == "blocked" or off_topic.get("verdict") == "blocked":
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="supervisor",
            session_id=session_id,
            decision="end_guardrail_blocked",
            duration_ms=elapsed,
        )
        return {"routing_tier": routing_tier, "next_node": "output_guardrails"}

    # --- Conversational intent → direct to conversational node ---
    if intent == "conversational":
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="supervisor",
            session_id=session_id,
            decision="conversational",
            duration_ms=elapsed,
        )
        return {"routing_tier": routing_tier, "next_node": "conversational"}

    # --- Confidence-ladder routing ---
    if routing_tier == "strict":
        if intent in ("cultural_query", "food_culture"):
            next_node = "rag_agent"
        elif intent in ("restaurant_search", "navigation"):
            next_node = "maps_agent"
        else:
            next_node = "rag_agent"
    elif routing_tier == "soft":
        # Soft tier uses LLM tool-calling via rag_agent (supervisor pattern)
        next_node = "rag_agent"
    else:
        # Fallback tier — route to conversational for safe handling
        next_node = "conversational"

    elapsed = round((time.perf_counter() - t0) * 1000, 3)
    logger.info(
        "graph.node_exit",
        node="supervisor",
        session_id=session_id,
        decision=next_node,
        routing_tier=routing_tier,
        duration_ms=elapsed,
    )
    return {"routing_tier": routing_tier, "next_node": next_node}


# ---------------------------------------------------------------------------
# 4. conversational_node (REAL)
# ---------------------------------------------------------------------------


async def conversational_node(state: AgentState) -> dict[str, Any]:
    """Handle conversational intents: greetings, capability questions, clarifications.

    Uses deterministic helpers from ``routing.py`` for direct answers.
    When the LLM client is available and the action is ``llm``, calls the
    LLM for a natural conversational response.

    Reads:
        - ``state["message"]``, ``state["history"]``, ``state["language"]``
    Writes:
        - ``response_text``, ``suggestions``, ``intent``
    """
    t0 = time.perf_counter()
    message = state.get("message", "")
    history = state.get("history", [])
    language = state.get("language", "vi")
    session_id = state.get("session_id", "")

    logger.info(
        "graph.node_enter",
        node="conversational",
        session_id=session_id,
    )

    action = _fallback_action(message, history)

    # --- Direct answer (greetings, capability questions) ---
    if action == "direct":
        response_text = _direct_answer(message, history, language)
        suggestions = _get_default_suggestions(
            intent="conversational",
            language=language,
        )
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="conversational",
            session_id=session_id,
            action="direct",
            duration_ms=elapsed,
        )
        return {
            "response_text": response_text,
            "suggestions": suggestions,
            "intent": "conversational",
        }

    # --- Clarification ---
    if action == "clarify":
        response_text = _clarify_message(language)
        suggestions = _get_default_suggestions(
            intent="clarification",
            language=language,
        )
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="conversational",
            session_id=session_id,
            action="clarify",
            duration_ms=elapsed,
        )
        return {
            "response_text": response_text,
            "suggestions": suggestions,
            "intent": "clarification",
        }

    # --- LLM path for general conversational ---
    services = get_services()
    client = services.llm_client
    if client is not None:
        try:
            messages = _messages_for_llm(
                message=message,
                history=history,
                language=language,
            )
            completion = await client.chat.completions.create(
                model=services.model,
                messages=messages,
                max_completion_tokens=512,
            )
            content = completion.choices[0].message.content or ""
            msg_text, suggestions = _extract_suggestions(content)
            if not msg_text:
                msg_text = _clarify_message(language)
            if not suggestions:
                suggestions = _get_default_suggestions(
                    intent="conversational",
                    language=language,
                )
            elapsed = round((time.perf_counter() - t0) * 1000, 3)
            logger.info(
                "graph.node_exit",
                node="conversational",
                session_id=session_id,
                action="llm",
                duration_ms=elapsed,
            )
            return {
                "response_text": msg_text,
                "suggestions": suggestions,
                "intent": state.get("intent") or "conversational",
            }
        except Exception as exc:
            logger.warning(
                "graph.node_error",
                node="conversational",
                session_id=session_id,
                error_type=type(exc).__name__,
                error=str(exc),
                mode="llm_failed_falling_back",
            )

    # --- Fallback: deterministic response ---
    response_text = _direct_answer(message, history, language)
    if not response_text:
        response_text = _clarify_message(language)
    suggestions = _get_default_suggestions(
        intent="conversational",
        language=language,
        fallback=True,
    )
    elapsed = round((time.perf_counter() - t0) * 1000, 3)
    logger.info(
        "graph.node_exit",
        node="conversational",
        session_id=session_id,
        action="fallback",
        duration_ms=elapsed,
    )
    return {
        "response_text": response_text,
        "suggestions": suggestions,
        "intent": state.get("intent") or "conversational",
    }


# ---------------------------------------------------------------------------
# 5. output_guardrails_node (REAL)
# ---------------------------------------------------------------------------


async def output_guardrails_node(state: AgentState) -> dict[str, Any]:
    """Verify that the response text is grounded in source material.

    Reads:
        - ``state["response_text"]``, ``state["citations"]``
    Writes:
        - ``guardrail_flags`` — updated with ``output_grounding`` verdict
    """
    t0 = time.perf_counter()
    session_id = state.get("session_id", "")
    response_text = state.get("response_text", "")

    logger.info(
        "graph.node_enter",
        node="output_guardrails",
        session_id=session_id,
    )

    flags: dict[str, Any] = dict(state.get("guardrail_flags") or {})

    # Skip grounding check for blocked/off-topic/conversational responses
    intent = state.get("intent")
    if intent in ("blocked", "off_topic", "conversational", "clarification"):
        flags["output_grounding"] = {
            "verdict": "skipped",
            "reason": f"intent_{intent}",
        }
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="output_guardrails",
            session_id=session_id,
            verdict="skipped",
            reason=f"intent_{intent}",
            duration_ms=elapsed,
        )
        return {"guardrail_flags": flags}

    citations = state.get("citations", [])
    grounding_result = verify_grounding(response_text, citations or None)

    flags["output_grounding"] = {
        "verdict": grounding_result.verdict,
        "reason": grounding_result.reason,
        "severity": grounding_result.severity,
        "details": grounding_result.details or "",
    }

    elapsed = round((time.perf_counter() - t0) * 1000, 3)
    logger.info(
        "graph.node_exit",
        node="output_guardrails",
        session_id=session_id,
        verdict=grounding_result.verdict,
        reason=grounding_result.reason,
        duration_ms=elapsed,
    )
    return {"guardrail_flags": flags}


# ---------------------------------------------------------------------------
# 6. rag_agent_node (REAL — hybrid retrieval + Cohere rerank + LLM answer)
# ---------------------------------------------------------------------------


async def rag_agent_node(state: AgentState) -> dict[str, Any]:
    """RAG agent node: retrieve, rerank, and generate a grounded answer.

    Pipeline:
        1. Retrieve top-10 chunks via the injected retriever (hybrid or BM25).
        2. Rerank with Cohere cross-encoder (top-5) when available.
        3. Build citations from the reranked chunks.
        4. Generate a grounded answer via LLMAnswerService when available.
        5. Fall back to deterministic text on any LLM or retrieval failure.

    Reads:
        - ``state["message"]``, ``state["rewritten_query"]``,
          ``state["language"]``, ``state["session_id"]``
    Writes:
        - ``knowledge_chunks``, ``citations``, ``response_text``,
          ``knowledge_response_ready``
    """
    t0 = time.perf_counter()
    message = state.get("rewritten_query") or state.get("message", "")
    language = state.get("language", "vi")
    session_id = state.get("session_id", "")

    logger.info(
        "graph.node_enter",
        node="rag_agent",
        session_id=session_id,
    )

    services = get_services()
    retriever = services.retriever
    cohere_reranker = services.cohere_reranker
    llm_answer_service = services.llm_answer_service

    # ------------------------------------------------------------------
    # Step 1: Retrieve top-10 chunks
    # ------------------------------------------------------------------
    chunks: list[Any] = []

    if retriever is not None:
        try:
            result = retriever.search(message, top_k=10)
            # Handle both sync (Retriever) and async (HybridRetriever)
            if inspect.isawaitable(result):
                result = await result
            chunks = list(result.chunks) if result else []
        except Exception as exc:
            logger.warning(
                "rag_agent.retrieve_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                session_id=session_id,
            )
            chunks = []

    # ------------------------------------------------------------------
    # Step 2: Rerank with Cohere cross-encoder (top-5)
    # ------------------------------------------------------------------
    if cohere_reranker is not None and chunks:
        try:
            chunks = await cohere_reranker.rerank(message, chunks, top_n=5)
        except Exception as exc:
            # CohereReranker already handles its own graceful degradation,
            # but catch any unexpected failure here too.
            logger.warning(
                "rag_agent.rerank_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                session_id=session_id,
            )
            chunks = chunks[:5]

    # ------------------------------------------------------------------
    # Step 3: Build citations from chunks
    # ------------------------------------------------------------------
    citations: list[Any] = [citation_from_chunk(c) for c in chunks]

    # ------------------------------------------------------------------
    # Step 4: Generate grounded answer via LLM
    # ------------------------------------------------------------------
    response_text = ""
    mode = "no_llm"

    if llm_answer_service is not None and chunks:
        try:
            response = await llm_answer_service.answer(
                chunks=chunks,
                citations=citations,
                query=message,
                language=language,
                session_id=session_id,
            )
            response_text = response.message
            mode = "llm"
        except Exception as exc:
            logger.warning(
                "rag_agent.llm_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                fallback=True,
                session_id=session_id,
            )
            response_text = ""
            mode = "llm_failed"

    # ------------------------------------------------------------------
    # Step 5: Fallback response when LLM unavailable or failed
    # ------------------------------------------------------------------
    if not response_text:
        if chunks:
            # Deterministic fallback: summarize first chunk(s)
            if language == "vi":
                response_text = (
                    f"Dựa trên thông tin có sẵn, đây là điều mình tìm được:\n\n"
                    f"**{chunks[0].title}**: {chunks[0].text[:300]}"
                )
                if len(chunks) > 1:
                    response_text += f"\n\n**{chunks[1].title}**: {chunks[1].text[:200]}"
            else:
                response_text = (
                    f"Based on available information, here is what I found:\n\n"
                    f"**{chunks[0].title}**: {chunks[0].text[:300]}"
                )
                if len(chunks) > 1:
                    response_text += f"\n\n**{chunks[1].title}**: {chunks[1].text[:200]}"
            mode = "deterministic"
        else:
            # No chunks available at all
            if language == "vi":
                response_text = (
                    "Mình chưa có thông tin cụ thể về khoản này, "
                    "nhưng bạn có thể hỏi thêm về văn hóa, lịch sử, "
                    "hoặc các địa điểm ở Hàm Ninh nhé!"
                )
            else:
                response_text = (
                    "I don't have specific information about this yet, "
                    "but feel free to ask about Ham Ninh's culture, history, "
                    "or places!"
                )
            mode = "no_chunks"

    elapsed = round((time.perf_counter() - t0) * 1000, 3)
    logger.info(
        "graph.node_exit",
        node="rag_agent",
        session_id=session_id,
        mode=mode,
        chunk_count=len(chunks),
        citation_count=len(citations),
        duration_ms=elapsed,
    )
    return {
        "knowledge_chunks": chunks,
        "citations": citations,
        "response_text": response_text,
        "knowledge_response_ready": True,
    }


# ---------------------------------------------------------------------------
# 7. grade_documents_node (REAL — LLM structured-output relevance grading)
# ---------------------------------------------------------------------------

_GRADE_DOCUMENTS_SYSTEM_PROMPT = """\
You are a document relevance grader for the Ham Ninh tourism assistant.
Given a retrieved document chunk and the user's question, determine whether \
the chunk contains information relevant to answering the question.

Respond with 'yes' if the chunk is relevant, 'no' if it is not.
Be lenient: if the chunk is even partially related to the question, mark it relevant.
"""


async def grade_documents_node(state: AgentState) -> dict[str, Any]:
    """Grade chunk relevance via LLM structured output for self-corrective RAG.

    For each retrieved chunk (limited to top-5 for latency), calls the LLM
    with ``response_format=GradeDocuments`` to produce a binary relevance
    score.  Aggregates individual scores into ``grade_score`` (mean) and
    ``grade_label`` ('relevant' if score >= 0.5, else 'irrelevant').

    Degrades gracefully:
    - No chunks → grade_score=0.0, grade_label='irrelevant'
    - No LLM client → grade_score=1.0, grade_label='relevant' (pass-through)
    - Per-chunk LLM failure → assume relevant (score 1.0), log warning

    Reads:
        - ``state["knowledge_chunks"]``, ``state["message"]``,
          ``state["session_id"]``
    Writes:
        - ``grade_score``, ``grade_label``
    """
    t0 = time.perf_counter()
    session_id = state.get("session_id", "")
    message = state.get("message", "")
    chunks = state.get("knowledge_chunks") or []

    logger.info(
        "graph.node_enter",
        node="grade_documents",
        session_id=session_id,
        chunk_count=len(chunks),
    )

    # --- No chunks: irrelevant by default ---
    if not chunks:
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="grade_documents",
            session_id=session_id,
            mode="no_chunks",
            grade_score=0.0,
            grade_label="irrelevant",
            duration_ms=elapsed,
        )
        return {
            "grade_score": 0.0,
            "grade_label": "irrelevant",
        }

    services = get_services()
    client = services.llm_client

    # --- No LLM client: pass-through as relevant ---
    if client is None or GradeDocuments is None:
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="grade_documents",
            session_id=session_id,
            mode="no_llm_passthrough",
            grade_score=1.0,
            grade_label="relevant",
            duration_ms=elapsed,
        )
        return {
            "grade_score": 1.0,
            "grade_label": "relevant",
        }

    # --- Grade each chunk (limit to top-5 for latency) ---
    import json as _json

    gradeable_chunks = chunks[:5]
    scores: list[float] = []

    for i, chunk in enumerate(gradeable_chunks):
        chunk_text = getattr(chunk, "text", "") or str(chunk)
        chunk_title = getattr(chunk, "title", "") or ""

        try:
            user_content = (
                f"Document title: {chunk_title}\n"
                f"Document content: {chunk_text}\n\n"
                f"User question: {message}"
            )

            completion = await client.chat.completions.parse(
                model=services.model,
                messages=[
                    {"role": "system", "content": _GRADE_DOCUMENTS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format=GradeDocuments,
                max_completion_tokens=32,
            )

            message = completion.choices[0].message
            if message.parsed:
                binary_score = message.parsed.binary_score
                score_value = 1.0 if binary_score == "yes" else 0.0
                scores.append(score_value)
            else:
                # Assume relevant on refusal/failure (optimistic)
                logger.warning(
                    "grade_documents.chunk_refused",
                    chunk_index=i,
                    refusal=message.refusal,
                    session_id=session_id,
                )
                scores.append(1.0)

        except Exception as exc:
            logger.warning(
                "grade_documents.chunk_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                chunk_index=i,
                session_id=session_id,
            )
            # Assume relevant on failure (optimistic: avoid unnecessary rewrite)
            scores.append(1.0)

    # --- Aggregate scores ---
    grade_score = sum(scores) / len(scores) if scores else 0.0
    grade_label = "relevant" if grade_score >= 0.5 else "irrelevant"

    elapsed = round((time.perf_counter() - t0) * 1000, 3)
    logger.info(
        "graph.node_exit",
        node="grade_documents",
        session_id=session_id,
        mode="llm",
        grade_score=round(grade_score, 3),
        grade_label=grade_label,
        chunks_graded=len(scores),
        duration_ms=elapsed,
    )
    return {
        "grade_score": grade_score,
        "grade_label": grade_label,
    }


# ---------------------------------------------------------------------------
# 8. rewrite_query_node (REAL — LLM structured-output query rewrite)
# ---------------------------------------------------------------------------

_REWRITE_QUERY_SYSTEM_PROMPT = """\
You are a query rewriter for the Ham Ninh tourism assistant's self-corrective RAG system.
When the initial retrieval returns irrelevant documents, rewrite the user's query to improve \
retrieval relevance while preserving the original intent and language (Vietnamese or English).

Make the query more specific and retrieval-friendly:
- Add location context (Hàm Ninh, Phú Quốc) when relevant
- Expand abbreviations or ambiguous terms
- Use more precise vocabulary for tourism domain
- Keep the query concise (under 50 words)

Respond with the rewritten query and a brief reasoning for the changes.
"""


async def rewrite_query_node(state: AgentState) -> dict[str, Any]:
    """Rewrite query via LLM structured output for self-corrective RAG.

    Calls the LLM with ``response_format=RewriteQuery`` to produce an improved
    query when initial retrieval returns irrelevant documents. Increments
    ``rewrite_count`` on each attempt (success or failure).

    Degrades gracefully:
    - No LLM client → return original message (no_llm_passthrough mode)
    - LLM failure → return original message and increment rewrite_count (llm_failed mode)
    - LLM timeout → return original message and increment rewrite_count (llm_failed mode)

    Reads:
        - ``state["message"]``, ``state["rewrite_count"]``, ``state["session_id"]``
    Writes:
        - ``rewritten_query``, ``rewrite_count``
    """
    t0 = time.perf_counter()
    session_id = state.get("session_id", "")
    message = state.get("message", "")
    rewrite_count = state.get("rewrite_count", 0)

    logger.info(
        "graph.node_enter",
        node="rewrite_query",
        session_id=session_id,
    )

    services = get_services()
    client = services.llm_client

    # --- No LLM client: pass-through with original message ---
    if client is None or RewriteQuery is None:
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="rewrite_query",
            session_id=session_id,
            mode="no_llm_passthrough",
            rewritten_query=message,
            reasoning="no_llm_client",
            duration_ms=elapsed,
        )
        return {
            "rewritten_query": message,
            "rewrite_count": rewrite_count,
        }

    # --- Call LLM with structured output ---
    import json as _json

    try:
        completion = await client.chat.completions.parse(
            model=services.model,
            messages=[
                {"role": "system", "content": _REWRITE_QUERY_SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            response_format=RewriteQuery,
            max_completion_tokens=128,
        )

        message_obj = completion.choices[0].message
        if message_obj.parsed:
            rewritten_query = message_obj.parsed.rewritten_query
            reasoning = message_obj.parsed.reasoning
        else:
            # Fallback to original message if parsing failed
            raise ValueError(f"LLM refused or failed to parse: {message_obj.refusal}")

        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="rewrite_query",
            session_id=session_id,
            mode="llm_rewrite",
            rewritten_query=rewritten_query,
            reasoning=reasoning,
            duration_ms=elapsed,
        )
        return {
            "rewritten_query": rewritten_query,
            "rewrite_count": rewrite_count + 1,
        }

    except Exception as exc:
        logger.warning(
            "rewrite_query.llm_failed",
            error_type=type(exc).__name__,
            error=str(exc),
            session_id=session_id,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="rewrite_query",
            session_id=session_id,
            mode="llm_failed",
            rewritten_query=message,
            reasoning=f"llm_error: {type(exc).__name__}",
            duration_ms=elapsed,
        )
        return {
            "rewritten_query": message,
            "rewrite_count": rewrite_count + 1,
        }


# ---------------------------------------------------------------------------
# 9. maps_agent_node (REAL — PlaceRecommendationService integration)
# ---------------------------------------------------------------------------


async def maps_agent_node(state: AgentState) -> dict[str, Any]:
    """Maps agent node: call PlaceRecommendationService for place recommendations.

    Calls the injected PlaceRecommendationService to retrieve fairness-ranked
    places with score_breakdown. Handles location consent and service failures
    gracefully.

    Reads:
        - ``state["message"]`` — user query text
        - ``state["user_location"]`` — optional dict with lat/lng
        - ``state["language"]`` — language code (default "vi")
        - ``state["session_id"]`` — session identifier
        - ``state["needs_location"]`` — whether location is required
    Writes:
        - ``places`` — list of place dicts with score_breakdown
        - ``response_text`` — natural language response message
    """
    t0 = time.perf_counter()
    session_id = state.get("session_id", "")
    message = state.get("message", "")
    user_location = state.get("user_location")
    language = state.get("language", "vi")
    needs_location = state.get("needs_location", False)
    budget_filter = state.get("budget_filter", None)
    accessibility_required = state.get("accessibility_required", True)

    logger.info(
        "graph.node_enter",
        node="maps_agent",
        session_id=session_id,
        mode="place_recommendation",
    )

    # Location consent check: if location is needed but not provided, prompt user
    if needs_location and user_location is None:
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="maps_agent",
            session_id=session_id,
            mode="location_consent_needed",
            duration_ms=elapsed,
        )
        consent_message = (
            "Để gợi ý địa điểm phù hợp gần bạn, mình cần biết vị trí hiện tại. "
            "Bạn có thể chia sẻ vị trí không?"
            if language == "vi"
            else "To recommend places near you, I need your current location. "
            "Can you share your location?"
        )
        return {
            "places": [],
            "response_text": consent_message,
        }

    # Get PlaceRecommendationService from dependency injection
    services = get_services()
    places_service = services.places_service

    if places_service is None:
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.warning(
            "graph.node_exit",
            node="maps_agent",
            session_id=session_id,
            mode="no_places_service",
            duration_ms=elapsed,
        )
        error_message = (
            "Xin lỗi, dịch vụ gợi ý địa điểm hiện không khả dụng. "
            "Vui lòng thử lại sau."
            if language == "vi"
            else "Sorry, the place recommendation service is currently unavailable. "
            "Please try again later."
        )
        return {
            "places": [],
            "response_text": error_message,
        }

    # Call PlaceRecommendationService
    try:
        chat_response = await places_service.recommend(
            query=message,
            user_location=user_location,
            language=language,
            session_id=session_id,
            budget=budget_filter,
            accessibility=accessibility_required,
        )

        # Convert PlaceResult Pydantic models to dicts for AgentState
        places_dicts = [place.model_dump() for place in chat_response.places]

        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="maps_agent",
            session_id=session_id,
            mode="place_recommendation",
            place_count=len(places_dicts),
            duration_ms=elapsed,
        )

        return {
            "places": places_dicts,
            "response_text": chat_response.message,
        }

    except Exception as exc:
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.error(
            "graph.node_exit",
            node="maps_agent",
            session_id=session_id,
            mode="service_error",
            error_type=type(exc).__name__,
            error=str(exc),
            duration_ms=elapsed,
        )
        error_message = (
            "Xin lỗi, đã xảy ra lỗi khi tìm kiếm địa điểm. "
            "Vui lòng thử lại sau."
            if language == "vi"
            else "Sorry, an error occurred while searching for places. "
            "Please try again later."
        )
        return {
            "places": [],
            "response_text": error_message,
        }
