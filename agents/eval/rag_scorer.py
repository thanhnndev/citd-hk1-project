"""Lightweight RAG quality scoring for realtime chat traces.

Computes deterministic metrics (no extra LLM calls) from RAG pipeline
outputs and logs them to the active Langfuse trace.  Designed to run
inside graph nodes without adding measurable latency.

Metrics logged:
    - rag.chunk_count: number of retrieved chunks used
    - rag.citation_count: number of citations generated
    - rag.response_length: character length of the response
    - rag.grounding_verdict: output guardrails verdict (categorical)
    - rag.retrieval_mode: how the answer was produced (llm, deterministic, cache, etc.)
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


def score_rag_trace(
    *,
    response_text: str,
    chunk_count: int,
    citation_count: int,
    grounding_verdict: str,
    retrieval_mode: str,
) -> None:
    """Log RAG quality scores to the active Langfuse trace.

    All parameters are pre-computed by the caller — this function only
    packages and sends them.  If Langfuse is disabled or no trace is
    active, the call is a silent no-op.
    """
    try:
        from langfuse import get_client

        client = get_client()
        if client is None:
            return

        # Numeric metrics
        client.score_current_trace(
            name="rag.chunk_count",
            value=chunk_count,
            data_type="NUMERIC",
        )
        client.score_current_trace(
            name="rag.citation_count",
            value=citation_count,
            data_type="NUMERIC",
        )
        client.score_current_trace(
            name="rag.response_length",
            value=len(response_text),
            data_type="NUMERIC",
        )

        # Categorical metrics
        client.score_current_trace(
            name="rag.grounding_verdict",
            value=grounding_verdict,
            data_type="CATEGORICAL",
        )
        client.score_current_trace(
            name="rag.retrieval_mode",
            value=retrieval_mode,
            data_type="CATEGORICAL",
        )

        client.flush()

        logger.debug(
            "rag.score.logged",
            chunk_count=chunk_count,
            citation_count=citation_count,
            response_length=len(response_text),
            grounding_verdict=grounding_verdict,
            retrieval_mode=retrieval_mode,
        )
    except Exception as exc:
        logger.warning(
            "rag.score.failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
