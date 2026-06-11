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
from agents.eval.rag_scorer import score_rag_trace
from agents.graph.helpers import *

logger = structlog.get_logger(__name__)
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

    # Skip document-grounding for responses that are not RAG document answers.
    # Place/map answers are grounded by provider place data, not citations.
    intent = state.get("intent")
    if intent in (
        "blocked", "off_topic", "conversational", "clarification",
        "restaurant_search", "navigation", "place_comparison",
    ):
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
        update: dict[str, Any] = {"guardrail_flags": flags}
        if response_text:
            update["messages"] = [{"role": "assistant", "content": response_text}]
        return update

    citations = state.get("citations", [])
    services = get_services()
    grounding_result = await verify_grounding(
        response_text,
        citations or None,
        services.llm_client,
        services.model,
        places=state.get("places", []),
    )

    flags["output_grounding"] = {
        "verdict": grounding_result.verdict,
        "reason": grounding_result.reason,
        "severity": grounding_result.severity,
        "details": grounding_result.details or "",
    }

    # Log RAG quality scores to Langfuse for knowledge intents
    if intent in {"cultural_query", "food_culture"}:
        tool_receipts = state.get("tool_receipts") or []
        retrieval_mode = "unknown"
        for receipt in tool_receipts:
            if isinstance(receipt, dict) and receipt.get("tool") == "knowledge_retriever":
                retrieval_mode = receipt.get("status", "unknown")
                break

        score_rag_trace(
            response_text=response_text,
            chunk_count=len(state.get("knowledge_chunks") or []),
            citation_count=len(citations),
            grounding_verdict=grounding_result.verdict,
            retrieval_mode=retrieval_mode,
        )

    elapsed = round((time.perf_counter() - t0) * 1000, 3)
    logger.info(
        "graph.node_exit",
        node="output_guardrails",
        session_id=session_id,
        verdict=grounding_result.verdict,
        reason=grounding_result.reason,
        duration_ms=elapsed,
    )
    update: dict[str, Any] = {"guardrail_flags": flags}
    if response_text:
        update["messages"] = [{"role": "assistant", "content": response_text}]
    return update


# ---------------------------------------------------------------------------
