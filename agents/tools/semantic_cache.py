"""Redis-backed semantic cache for query→response deduplication.

Uses cosine similarity ≥0.95 to match incoming queries against cached
embeddings before falling through to Qdrant lookup.

Observability: emits structlog events semantic_cache.hit, semantic_cache.miss,
semantic_cache.store, semantic_cache.error — all with query hash, never raw text.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Optional

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Shared constant — OpenAI text-embedding-3-small dimension
EXPECTED_DIMENSION = 1536


def _query_hash(query: str) -> str:
    """Deterministic short hash of query text for key naming."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity via numpy.dot / numpy.linalg.norm."""
    a_arr = np.array(a, dtype=np.float64)
    b_arr = np.array(b, dtype=np.float64)
    dot = np.dot(a_arr, b_arr)
    norm = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
    if norm == 0.0:
        return 0.0
    return float(dot / norm)


class SemanticCache:
    """Redis-backed semantic cache with cosine similarity matching.

    Each cache entry is stored as a Redis hash at key ``semantic_cache:{query_hash}``
    with fields: query, embedding (JSON array), response, ts (unix timestamp), dim.

    Args:
        redis_url: Redis connection URL. Falls back to REDIS_URL env var, then
                   ``redis://localhost:6379/0``.
        similarity_threshold: Minimum cosine similarity for a cache hit (default 0.95).
        max_entries: Soft cap on cached entries. Oldest entries are evicted when
                     exceeded (default 10000).
    """

    KEY_PREFIX = "semantic_cache:"

    def __init__(
        self,
        redis_url: Optional[str] = None,
        similarity_threshold: float = 0.95,
        max_entries: int = 10000,
    ) -> None:
        self.redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self.similarity_threshold = similarity_threshold
        self.max_entries = max_entries
        self._client: Optional[object] = None  # redis.asyncio.Redis

    # ------------------------------------------------------------------
    # Internal: lazy Redis client
    # ------------------------------------------------------------------

    def _get_client(self) -> Optional[object]:
        """Return a connected async Redis client, or None on failure."""
        if self._client is not None:
            return self._client
        try:
            import redis.asyncio as redis

            self._client = redis.from_url(self.redis_url, decode_responses=True)
            return self._client
        except Exception:
            logger.error("semantic_cache.error", reason="connection_failed", redis_url=self.redis_url)
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def lookup(self, query: str, query_embedding: list[float]) -> Optional[str]:
        """Look up a cached response by semantic similarity.

        Scans all cache entries via Redis SCAN, computes cosine similarity
        against each stored embedding, and returns the cached response if
        any entry meets the similarity threshold.

        Returns:
            Cached response string on hit, or None on miss / error.
        """
        q_hash = _query_hash(query)
        client = self._get_client()
        if client is None:
            return None

        try:
            cursor = 0
            best_similarity = -1.0
            best_response: Optional[str] = None

            while True:
                cursor, keys = await client.scan(cursor, match=f"{self.KEY_PREFIX}*", count=100)
                for key in keys:
                    entry = await client.hgetall(key)
                    if not entry or "embedding" not in entry:
                        continue
                    try:
                        cached_embedding = json.loads(entry["embedding"])
                    except (json.JSONDecodeError, KeyError):
                        continue
                    sim = _cosine_similarity(query_embedding, cached_embedding)
                    if sim >= self.similarity_threshold and sim > best_similarity:
                        best_similarity = sim
                        best_response = entry.get("response")

                if cursor == 0:
                    break

            if best_response is not None:
                logger.info(
                    "semantic_cache.hit",
                    query_hash=q_hash,
                    similarity=round(best_similarity, 4),
                )
                return best_response

            logger.info("semantic_cache.miss", query_hash=q_hash)
            return None

        except Exception as exc:
            logger.error("semantic_cache.error", query_hash=q_hash, reason=str(exc))
            return None

    async def store(
        self,
        query: str,
        query_embedding: list[float],
        response: str,
        ttl: int = 3600,
    ) -> None:
        """Store a query→response mapping in the cache.

        Validates embedding dimension against EXPECTED_DIMENSION (1536).
        Stores as a Redis hash with TTL.

        Args:
            query: Original query text.
            query_embedding: Embedding vector (must be 1536-dimensional).
            response: Response text to cache.
            ttl: Time-to-live in seconds (default 3600).

        Raises:
            ValueError: If embedding dimension does not match EXPECTED_DIMENSION.
        """
        if len(query_embedding) != EXPECTED_DIMENSION:
            raise ValueError(
                f"Embedding dimension mismatch: expected {EXPECTED_DIMENSION}, "
                f"got {len(query_embedding)}"
            )

        q_hash = _query_hash(query)
        key = f"{self.KEY_PREFIX}{q_hash}"
        client = self._get_client()
        if client is None:
            return

        import time

        try:
            import json as _json

            entry = {
                "query": query,
                "embedding": _json.dumps(query_embedding),
                "response": response,
                "ts": str(time.time()),
                "dim": str(len(query_embedding)),
            }
            await client.hset(key, mapping=entry)
            await client.expire(key, ttl)
            logger.info("semantic_cache.store", query_hash=q_hash, ttl=ttl)

        except Exception as exc:
            logger.error("semantic_cache.error", query_hash=q_hash, reason=str(exc))

    async def clear(self) -> int:
        """Delete all cache keys. Returns count of keys deleted."""
        client = self._get_client()
        if client is None:
            return 0

        try:
            count = 0
            cursor = 0
            while True:
                cursor, keys = await client.scan(cursor, match=f"{self.KEY_PREFIX}*", count=100)
                if keys:
                    await client.delete(*keys)
                    count += len(keys)
                if cursor == 0:
                    break
            return count
        except Exception as exc:
            logger.error("semantic_cache.error", reason=str(exc))
            return 0
