"""Deterministic keyword retriever over normalized RAG chunks.

Provides a BM21-style (TF * IDF) in-memory search interface with
reliability-boosted scoring and latency measurement.  Re-exports
``load_corpus`` so downstream code imports from a single surface.
"""

from __future__ import annotations

import re
import time
from typing import List

from app.models.rag import RAGChunk, RetrievalResult
from app.models.response import Citation

# Re-export for single-import convenience
from agents.tools.corpus_loader import load_corpus  # noqa: F401

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Simple whitespace + punctuation tokenizer — deterministic, no stemming,
# no accent normalization (keeps Vietnamese tokens intact for exact match).
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _tokenize(text: str) -> List[str]:
    """Lowercase, alphanumeric token extraction."""
    return _TOKEN_RE.findall(text.lower())


def _idf(doc_freq: int, num_docs: int) -> float:
    """Inverse document frequency (smoothed log variant)."""
    import math

    return math.log((num_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)


# ---------------------------------------------------------------------------
# Citation helper
# ---------------------------------------------------------------------------

def citation_from_chunk(chunk: RAGChunk) -> Citation:
    """Map an RAGChunk to a Citation response model.

    title -> source
    url   -> url
    text  -> snippet (first 200 characters)
    """
    return Citation(
        source=chunk.title,
        url=chunk.url,
        snippet=chunk.text[:200] if len(chunk.text) > 200 else chunk.text,
    )


# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------

RELIABILITY_BOOST = {"high": 1.1, "medium": 1.0, "low": 0.95}


class Retriever:
    """In-memory keyword retriever over a corpus of RAGChunks.

    Scoring: BM21-style TF * IDF with reliability multiplier.
    Deterministic: same query + corpus → identical ordered results.
    """

    def __init__(self, chunks: list[RAGChunk]) -> None:
        self._chunks = chunks

        # Build inverted index: token -> set of chunk indices
        self._index: dict[str, set[int]] = {}
        # Per-chunk term frequencies
        self._tf: list[dict[str, int]] = []

        for idx, chunk in enumerate(chunks):
            tokens = _tokenize(chunk.text)
            tf: dict[str, int] = {}
            for tok in tokens:
                tf[tok] = tf.get(tok, 0) + 1
            self._tf.append(tf)
            for tok in tf:
                self._index.setdefault(tok, set()).add(idx)

        # Number of unique "documents" for IDF (each chunk is a doc)
        self._num_docs = len(chunks)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 5) -> RetrievalResult:
        """Keyword search returning ranked results.

        Args:
            query: Free-text search string.
            top_k: Maximum number of results to return.

        Returns:
            RetrievalResult with ranked chunks, total_found, and latency_ms.
        """
        t0 = time.perf_counter()

        tokens = _tokenize(query)
        if not tokens:
            elapsed = (time.perf_counter() - t0) * 1000
            return RetrievalResult(
                chunks=[],
                query=query,
                total_found=0,
                latency_ms=round(elapsed, 3),
            )

        # Score each chunk that has at least one query token
        scores: dict[int, float] = {}
        for token in tokens:
            doc_indices = self._index.get(token, set())
            for idx in doc_indices:
                tf_val = self._tf[idx].get(token, 0)
                df_val = len(doc_indices)
                idf_val = _idf(df_val, self._num_docs)
                base_score = tf_val * idf_val

                # Reliability multiplier
                if idx < len(self._chunks):
                    tier = self._chunks[idx].reliability
                    multiplier = RELIABILITY_BOOST.get(tier, 1.0)
                else:
                    multiplier = 1.0

                scores[idx] = scores.get(idx, 0.0) + base_score * multiplier

        # Deterministic ordering: primary by score descending,
        # secondary by chunk_id ascending (stable tie-breaking)
        ranked = sorted(
            scores.keys(),
            key=lambda idx: (-scores[idx], self._chunks[idx].chunk_id),
        )

        top_indices = ranked[:top_k]
        top_chunks = [self._chunks[i] for i in top_indices]

        elapsed = (time.perf_counter() - t0) * 1000
        return RetrievalResult(
            chunks=top_chunks,
            query=query,
            total_found=len(scores),
            latency_ms=round(elapsed, 3),
        )

    def search_with_citations(
        self, query: str, top_k: int = 5
    ) -> tuple[RetrievalResult, list[Citation]]:
        """Search and return both ranked results and their citations.

        Convenience for S02 chat endpoint integration.

        Returns:
            Tuple of (RetrievalResult, list[Citation]).
        """
        result = self.search(query, top_k=top_k)
        citations = [citation_from_chunk(c) for c in result.chunks]
        return result, citations
