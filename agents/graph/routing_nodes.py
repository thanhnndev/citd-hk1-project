from __future__ import annotations

import hashlib
import inspect
import json
import math
import time
from typing import Any, Literal

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from app.models.rag import RAGChunk
from app.models.response import Citation
from agents.graph.state import AgentState, RouterOutput
from agents.guardrails.input_guardrails import block_injection, reject_off_topic
from agents.guardrails.output_guardrails import verify_grounding
from agents.graph.routing import (_clarify_message, _direct_answer, _extract_suggestions, _fallback_action, _get_default_suggestions, _messages_for_llm)
from agents.tools.retriever import citation_from_chunk
from agents.graph.dependencies import NodeServices, configure_services, get_services
from agents.graph.helpers import *

logger = structlog.get_logger(__name__)
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
            "blocked": True,
            "run_status": "failed-terminal",
        }

    # --- Off-topic check ---
    services = get_services()
    topic_result = await reject_off_topic(message, services.llm_client, services.model)
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
            "blocked": True,
            "run_status": "failed-terminal",
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

def _checkpoint_history(state: AgentState) -> list[dict[str, str]]:
    """Return prior chat turns from checkpointed messages, excluding current user turn."""
    explicit_history = state.get("history") or []
    if explicit_history:
        return explicit_history

    current_message = state.get("message", "")
    raw_messages = state.get("messages") or []
    history: list[dict[str, str]] = []
    for item in raw_messages:
        role = None
        content = None
        if isinstance(item, dict):
            role = item.get("role")
            content = item.get("content")
        elif hasattr(item, "type") and hasattr(item, "content"):
            content = item.content
            if item.type == "human":
                role = "user"
            elif item.type == "ai":
                role = "assistant"
            else:
                role = item.type
        
        if role not in {"user", "assistant"} or not content:
            continue
        if role == "user" and content == current_message:
            continue
        history.append({"role": role, "content": str(content)})
    return history[-12:]


_INTENT_ROUTER_SYSTEM_PROMPT = """\
You are an intent classifier for the Ham Ninh tourism assistant.
Classify the user's message into one of these intents:
- cultural_query: questions about culture, history, fishing life, local food background
- food_culture: specifically about food traditions, recipes, local specialties
- restaurant_search: finding restaurants, cafes, hotels, places, directions, maps
  Also use this for requests asking where to go with children/family, because
  concrete venue suitability must be checked against provider place data.
- navigation: asking for directions, routes, maps
- conversational: greetings, thanks, capability questions, simple acknowledgments
- unknown: anything that does not fit the above

Also determine:
- confidence: your confidence in the classification (0.0 to 1.0)
- is_followup: whether the message references prior conversation context
- needs_location: whether the query requires the user's current GPS.
  Set true for local/deictic requests such as "near me", "nearby", "nearest",
  "around here", "gần đây", "gần tôi", "quanh đây", "từ vị trí của tôi",
  or "give me directions from where I am".
  Set false for route questions that already include an explicit origin, e.g.
  "Từ Dương Đông đi Hàm Ninh thế nào?" because no user GPS is needed.
Examples:
- "Tìm quán hải sản gần đây" -> restaurant_search, high confidence, needs_location=true
- "Có quán ăn nào gần tôi không?" -> restaurant_search, high confidence, needs_location=true
- "Tìm nhà hàng hải sản ở Hàm Ninh" -> restaurant_search, high confidence, needs_location=false
- "Đi với trẻ em nên ghé đâu?" -> restaurant_search, high confidence, needs_location=false
"""


async def intent_router_node(state: AgentState) -> dict[str, Any]:
    """Classify user intent via LLM structured output or heuristic fallback.

    When the LLM client is available, calls OpenAI with
    ``response_format=RouterOutput`` for structured classification.
    Falls back to deterministic heuristic routing when unavailable.

    Reads:
        - ``state["message"]``, ``state["history"]``, ``state["language"]``
    Writes:
        - ``intent``, ``intent_confidence``, ``needs_location``
    """
    t0 = time.perf_counter()
    message = state.get("message", "")
    history = _checkpoint_history(state)
    language = state.get("language", "vi")
    session_id = state.get("session_id", "")
    query_hash = _hash_query(message)

    logger.info(
        "graph.node_enter",
        node="intent_router",
        session_id=session_id,
        query_hash=query_hash,
    )

    if _is_place_comparison_followup(message, state):
        return {
            "intent": "restaurant_search",
            "intent_confidence": 1.0,
            "is_followup": True,
            "needs_location": False,
            "current_step": "places",
        }

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
            original_message = message
            messages.append({"role": "user", "content": original_message})

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
                model_needs_location = bool(message.parsed.needs_location)
                needs_location = _resolve_needs_location(original_message, model_needs_location)
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
                model_needs_location=model_needs_location,
                enforced_needs_location=needs_location,
                mode="llm",
                duration_ms=elapsed,
            )
            return {
                "intent": intent_label,
                "intent_confidence": confidence,
                "is_followup": is_followup,
                "needs_location": needs_location,
                "current_step": (
                    "knowledge"
                    if intent_label in {"cultural_query", "food_culture"}
                    else "places"
                    if intent_label in {"restaurant_search", "navigation"}
                    else "conversational"
                ),
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
            "trẻ em", "trẻ nhỏ", "gia đình", "children", "kids", "family",
            "ghé đâu", "đi đâu", "where should",
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

    needs_location = requires_user_location_heuristic(message)

    elapsed = round((time.perf_counter() - t0) * 1000, 3)
    logger.info(
        "graph.node_exit",
        node="intent_router",
        session_id=session_id,
        intent=intent_label,
        confidence=confidence,
        mode="heuristic",
        duration_ms=elapsed,
    )
    return {
        "intent": intent_label,
        "intent_confidence": confidence,
        "is_followup": bool(history),
        "needs_location": needs_location,
        "current_step": (
            "knowledge"
            if intent_label in {"cultural_query", "food_culture"}
            else "places"
            if intent_label in {"restaurant_search", "navigation"}
            else "conversational"
        ),
    }


# ---------------------------------------------------------------------------
