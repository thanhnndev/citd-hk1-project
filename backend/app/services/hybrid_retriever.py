"""BM25 sparse vectorizer and HybridRetriever for hybrid dense+sparse retrieval.

BM25Vectorizer is fit once at startup against the full corpus and then reused
for both corpus upsert (encoding each chunk into a SparseVector) and query
encoding (encoding the user query before sending to Qdrant).

HybridRetriever wraps QdrantService hybrid_search with a keyword-only fallback
so the chat router always gets a RetrievalResult regardless of Qdrant availability.

Typical lifecycle
-----------------
1. ``vectorizer = BM25Vectorizer()``
2. ``vectorizer.fit([chunk.text for chunk in chunks])``   # once, at lifespan
3. ``sparse_vec = vectorizer.encode(chunk.text)``         # per upsert point
4. ``sparse_vec = vectorizer.encode(query)``              # per search query
5. ``retriever = HybridRetriever(qdrant_svc, embed_svc, vectorizer, fallback)``
6. ``result = await retriever.search(query)``
"""

from __future__ import annotations

import math
import re
import time
from typing import List

import structlog
from qdrant_client.models import SparseVector

from app.models.rag import RAGChunk, RetrievalResult
from app.models.response import Citation
from app.services.retriever import Retriever, citation_from_chunk

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Tokenizer — identical pattern to retriever.py for consistent token space
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _tokenize(text: str) -> List[str]:
    """Lowercase, alphanumeric token extraction (no stemming, keeps Vietnamese)."""
    return _TOKEN_RE.findall(text.lower())


# ---------------------------------------------------------------------------
# BM25Vectorizer
# ---------------------------------------------------------------------------


class BM25Vectorizer:
    """In-process BM25 sparse vectorizer.

    Parameters
    ----------
    k1 : float
        Term-frequency saturation parameter (default 1.5).
    b : float
        Length normalization parameter (default 0.75).
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

        # Populated by fit()
        self._vocab: dict[str, int] = {}   # token -> integer index
        self._idf: dict[str, float] = {}   # token -> IDF score
        self._avgdl: float = 0.0

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def fit(self, texts: List[str]) -> None:
        """Build vocabulary and IDF table from a corpus of texts.

        Args:
            texts: List of document strings (e.g. chunk texts).
        """
        N = len(texts)
        if N == 0:
            return

        # Tokenize all documents
        tokenized: List[List[str]] = [_tokenize(t) for t in texts]

        # Average document length
        total_tokens = sum(len(toks) for toks in tokenized)
        self._avgdl = total_tokens / N

        # Document frequency per token
        df: dict[str, int] = {}
        for toks in tokenized:
            for tok in set(toks):
                df[tok] = df.get(tok, 0) + 1

        # Build vocab (sorted for determinism) and IDF
        self._vocab = {tok: idx for idx, tok in enumerate(sorted(df.keys()))}
        self._idf = {
            tok: math.log((N - freq + 0.5) / (freq + 0.5) + 1.0)
            for tok, freq in df.items()
        }

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------

    def encode(self, text: str) -> SparseVector:
        """Encode a single text into a BM25 SparseVector.

        Only tokens present in the fitted vocabulary contribute to the vector.
        Empty text or no vocabulary overlap returns an empty SparseVector.

        Args:
            text: Input string to encode.

        Returns:
            SparseVector with parallel ``indices`` and ``values`` lists.
        """
        if not self._vocab:
            return SparseVector(indices=[], values=[])

        tokens = _tokenize(text)
        if not tokens:
            return SparseVector(indices=[], values=[])

        # Term frequency in this document
        tf: dict[str, int] = {}
        for tok in tokens:
            tf[tok] = tf.get(tok, 0) + 1

        dl = len(tokens)
        norm = 1.0 - self.b + self.b * (dl / self._avgdl) if self._avgdl > 0 else 1.0

        indices: list[int] = []
        values: list[float] = []

        for tok, freq in tf.items():
            if tok not in self._vocab:
                continue
            idf_val = self._idf[tok]
            # BM25 TF component with length normalization
            tf_norm = (freq * (self.k1 + 1.0)) / (freq + self.k1 * norm)
            score = idf_val * tf_norm
            if score > 0:
                indices.append(self._vocab[tok])
                values.append(score)

        return SparseVector(indices=indices, values=values)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def vocab_size(self) -> int:
        """Number of unique tokens in the fitted vocabulary."""
        return len(self._vocab)


# ---------------------------------------------------------------------------
# HybridRetriever
# ---------------------------------------------------------------------------


class HybridRetriever:
    """Hybrid dense+sparse retriever with keyword-only fallback.

    Combines Qdrant RRF-fused search (dense embedding + BM25 sparse) with
    an in-memory keyword fallback so the chat router always receives a
    RetrievalResult even when Qdrant is unavailable.

    Args:
        qdrant_service: QdrantService instance with hybrid_search().
        embedding_service: EmbeddingService instance with embed_query().
        bm25: Fitted BM25Vectorizer for sparse query encoding.
        fallback: In-memory Retriever used when Qdrant is unreachable.
    """

    def __init__(
        self,
        qdrant_service: "QdrantService",  # type: ignore[name-defined]
        embedding_service: "EmbeddingService",  # type: ignore[name-defined]
        bm25: BM25Vectorizer,
        fallback: Retriever,
    ) -> None:
        self._qdrant = qdrant_service
        self._embed = embedding_service
        self._bm25 = bm25
        self._fallback = fallback

    async def dense_search(
        self, query: str, top_k: int = 5
    ) -> RetrievalResult:
        """Dense-only search (no sparse/BM25 required).

        Runs embedding + ``QdrantService.dense_search()`` and builds RAGChunk
        objects.  Returns an empty RetrievalResult on any Qdrant error,
        letting the caller decide whether to fall back to keyword search.

        Args:
            query: User's natural-language query.
            top_k: Maximum number of results to return.

        Returns:
            RetrievalResult with ranked chunks, total_found, query, latency_ms.
        """
        t0 = time.perf_counter()
        dense_vector = await self._embed.embed_query(query)
        scored_points = await self._qdrant.dense_search(dense_vector, top_k)

        chunks: list[RAGChunk] = []
        for point in scored_points:
            payload = point.payload or {}
            chunks.append(
                RAGChunk(
                    chunk_id=payload.get("chunk_id", ""),
                    source_id=payload.get("source_id", ""),
                    title=payload.get("title", ""),
                    url=payload.get("url"),
                    domain=payload.get("domain", ""),
                    source_type=payload.get("source_type", ""),
                    reliability=payload.get("reliability", "medium"),
                    language=payload.get("language", "vi"),
                    location=payload.get("location", ""),
                    text=payload.get("text", ""),
                    chunk_index=payload.get("chunk_index", 0),
                    total_chunks=payload.get("total_chunks", 1),
                )
            )

        latency_ms = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "agent.retrieval_mode",
            mode="dense",
            query=query,
            top_k=top_k,
            result_count=len(chunks),
            latency_ms=latency_ms,
        )
        return RetrievalResult(
            chunks=chunks,
            query=query,
            total_found=len(chunks),
            latency_ms=latency_ms,
        )

    async def search(self, query: str, top_k: int = 5) -> RetrievalResult:
        """Run dense-only search, falling back to keyword search on any Qdrant error.

        The sparse/BM25 path is entirely bypassed — the method calls
        ``dense_search()`` first and only touches the keyword fallback when
        Qdrant is unavailable or the collection has no sparse vector.

        Args:
            query: User's natural-language query.
            top_k: Maximum number of results to return.

        Returns:
            RetrievalResult with ranked chunks, total_found, query, latency_ms.
        """
        t0 = time.perf_counter()
        try:
            result = await self.dense_search(query, top_k)
            # dense_search already logged agent.retrieval_mode=dense
            return result

        except Exception as exc:
            latency_ms = round((time.perf_counter() - t0) * 1000, 3)
            logger.warning(
                "hybrid.qdrant_unavailable",
                error=str(exc),
                fallback=True,
                latency_ms=latency_ms,
            )
            return self._fallback.search(query, top_k)

    async def search_with_citations(
        self, query: str, top_k: int = 5
    ) -> tuple[RetrievalResult, list[Citation]]:
        """Search and return both ranked results and their citations.

        Args:
            query: User's natural-language query.
            top_k: Maximum number of results to return.

        Returns:
            Tuple of (RetrievalResult, list[Citation]).
        """
        result = await self.search(query, top_k=top_k)
        citations = [citation_from_chunk(c) for c in result.chunks]
        return result, citations

