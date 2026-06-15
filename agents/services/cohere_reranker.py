"""Cohere cross-encoder reranker service for hybrid retrieval results.

Reranks retrieved chunks using Cohere's rerank-v4.0-pro model to improve
relevance ordering based on query-document semantic similarity.

Graceful degradation: on any Cohere API failure, logs the error and returns
the original chunks truncated to top_n, allowing the pipeline to continue
with the initial retrieval ordering.

Typical lifecycle
-----------------
1. ``reranker = CohereReranker()``
2. ``reranked_chunks = await reranker.rerank(query, chunks, top_n=5)``
"""

from __future__ import annotations

import time
from typing import List

import cohere
import structlog

from app.core.config import get_settings
from app.models.rag import RAGChunk

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# CohereReranker
# ---------------------------------------------------------------------------


class CohereReranker:
    """Async cross-encoder reranker using Cohere's rerank-v4.0-pro model.

    Reranks a list of RAGChunks based on semantic relevance to a query.
    On any API failure, falls back to returning the original chunks
    truncated to top_n, ensuring the pipeline never breaks.

    Args:
        api_key: Cohere API key. If not provided, loads from config.
        model: Rerank model name (default: 'rerank-v4.0-pro').

    Usage::

        reranker = CohereReranker()
        reranked = await reranker.rerank(
            query="What are the best seafood restaurants?",
            chunks=retrieved_chunks,
            top_n=5,
        )
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "rerank-v4.0-pro",
    ) -> None:
        if api_key is not None:
            self._api_key = api_key
        else:
            settings = get_settings()
            self._api_key = settings.COHERE_API_KEY
        self._model = model
        self._client = cohere.AsyncClientV2(api_key=self._api_key) if self._api_key else None

    async def rerank(
        self,
        query: str,
        chunks: List[RAGChunk],
        top_n: int = 5,
    ) -> List[RAGChunk]:
        """Rerank chunks by semantic relevance to the query.

        Uses Cohere's cross-encoder model to score each chunk's relevance
        to the query, then returns them in descending relevance order.

        On any exception (auth error, rate limit, timeout, network failure),
        logs a structured warning and returns chunks[:top_n] as fallback.

        Args:
            query: User's natural-language query.
            chunks: List of RAGChunk objects from hybrid retrieval.
            top_n: Maximum number of chunks to return.

        Returns:
            List of RAGChunk objects reordered by relevance score.
        """
        t0 = time.perf_counter()

        # Handle edge cases
        if not chunks:
            return []

        if not self._api_key:
            logger.warning(
                "cohere.no_api_key",
                fallback=True,
            )
            return chunks[:top_n]

        # Extract text content for reranking
        documents = [chunk.text for chunk in chunks]

        try:
            # Call Cohere v2 rerank API
            response = await self._client.rerank(
                query=query,
                documents=documents,
                model=self._model,
                top_n=top_n,
            )

            # Extract ranked results
            results = response.results
            reranked_chunks: List[RAGChunk] = []

            for result in results:
                # result.index points to the original chunk position
                # result.relevance_score is the semantic relevance score
                original_index = result.index
                reranked_chunks.append(chunks[original_index])

            elapsed = time.perf_counter() - t0
            latency_ms = round(elapsed * 1000, 3)

            # Extract top score for observability
            top_score = results[0].relevance_score if results else 0.0

            logger.info(
                "cohere.rerank_success",
                input_count=len(chunks),
                output_count=len(reranked_chunks),
                top_score=top_score,
                latency_ms=latency_ms,
                query_length=len(query),
            )

            return reranked_chunks

        except Exception as exc:
            elapsed = time.perf_counter() - t0
            latency_ms = round(elapsed * 1000, 3)
            error_type = type(exc).__name__

            logger.warning(
                "cohere.rerank_failed",
                error_type=error_type,
                error=str(exc),
                fallback=True,
                latency_ms=latency_ms,
                input_count=len(chunks),
            )

            # Graceful degradation: return original chunks truncated to top_n
            return chunks[:top_n]
