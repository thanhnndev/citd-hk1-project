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
from agents.graph.routing_nodes import _checkpoint_history

logger = structlog.get_logger(__name__)
# 3. conversational_node
# ---------------------------------------------------------------------------


async def conversational_node(state: AgentState) -> dict[str, Any]:
    """Handle conversational intents: greetings, capability questions, clarifications.

    Uses deterministic helpers from ``routing.py`` for direct answers.
    When the LLM client is available and the action is ``llm``, calls the
    LLM for a natural conversational response.

    Reads:
        - ``state["message"]``, ``state["messages"]``, ``state["language"]``
    Writes:
        - ``response_text``, ``suggestions``, ``
    """
    t0 = time.perf_counter()
    message = state.get("message", "")
    history = _checkpoint_history(state)
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

    domain_action = _conversational_domain_action(message, history)
    if domain_action in {"clarify", "refuse"}:
        response_text = (
            _domain_context_clarification_message(language)
            if domain_action == "clarify"
            else _domain_refusal_message(language)
        )
        intent = "clarification" if domain_action == "clarify" else "off_topic"
        suggestions = _get_default_suggestions(
            intent=intent,
            language=language,
            fallback=True,
        )
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="conversational",
            session_id=session_id,
            action=f"domain_{domain_action}",
            duration_ms=elapsed,
        )
        return {
            "response_text": response_text,
            "suggestions": suggestions,
            "intent": intent,
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
            writer = None
            try:
                from langgraph.config import get_stream_writer
                writer = get_stream_writer()
            except Exception:
                writer = None

            if writer is not None:
                stream = await client.chat.completions.create(
                    model=services.model,
                    messages=messages,
                    max_completion_tokens=512,
                    stream=True,
                )
                content_parts: list[str] = []
                pending = ""
                suggestions_marker = "[SUGGESTIONS]"
                marker_seen = False
                async for chunk in stream:
                    token = chunk.choices[0].delta.content or ""
                    if token:
                        content_parts.append(token)
                        if marker_seen:
                            continue
                        pending += token
                        if suggestions_marker in pending:
                            visible, _ = pending.split(suggestions_marker, 1)
                            if visible:
                                writer({"type": "token", "content": visible})
                            pending = ""
                            marker_seen = True
                            continue
                        safe_length = max(0, len(pending) - len(suggestions_marker) + 1)
                        if safe_length:
                            writer({"type": "token", "content": pending[:safe_length]})
                            pending = pending[safe_length:]
                if pending and not marker_seen:
                    writer({"type": "token", "content": pending})
                content = "".join(content_parts)
            else:
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
