"""Tests for agents.tools.semantic_cache.

Uses fakeredis for Redis mocking — no live Redis required.
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.tools.semantic_cache import (
    EXPECTED_DIMENSION,
    SemanticCache,
    _cosine_similarity,
    _query_hash,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_embedding(dim: int = EXPECTED_DIMENSION, seed: int = 42) -> list[float]:
    """Generate a deterministic embedding for tests."""
    import random
    random.seed(seed)
    vec = [random.random() for _ in range(dim)]
    # Normalise so cosine sim with itself is ~1.0
    norm = sum(v * v for v in vec) ** 0.5
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def _near_embedding(base: list[float], noise: float = 0.01) -> list[float]:
    """Produce an embedding very close to *base* (similarity > 0.99)."""
    import random
    random.seed(99)
    return [v + random.uniform(-noise, noise) for v in base]


def _far_embedding(base: list[float]) -> list[float]:
    """Produce an embedding far from *base* (similarity well below 0.95)."""
    import random
    random.seed(77)
    return [v + random.uniform(-0.5, 0.5) for v in base]


# ---------------------------------------------------------------------------
# Cosine similarity unit tests
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 0.0, 0.0]
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert _cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-9)

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert _cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector(self):
        a = [0.0, 0.0]
        b = [1.0, 0.0]
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    def test_high_dimensional_similar(self):
        base = _random_embedding()
        near = _near_embedding(base)
        sim = _cosine_similarity(base, near)
        assert sim > 0.95

    def test_high_dimensional_dissimilar(self):
        base = _random_embedding()
        far = _far_embedding(base)
        sim = _cosine_similarity(base, far)
        # With enough random noise, similarity should be below threshold
        assert sim < 0.95


class TestQueryHash:
    def test_deterministic(self):
        assert _query_hash("hello") == _query_hash("hello")

    def test_different_inputs(self):
        assert _query_hash("hello") != _query_hash("world")

    def test_length(self):
        assert len(_query_hash("test")) == 16


# ---------------------------------------------------------------------------
# SemanticCache construction
# ---------------------------------------------------------------------------

class TestSemanticCacheConstruction:
    def test_importable_without_redis(self):
        """Class must be importable even if Redis is not running."""
        cache = SemanticCache(redis_url="redis://localhost:6379/0")
        assert cache.similarity_threshold == 0.95
        assert cache.max_entries == 10000

    def test_custom_threshold(self):
        cache = SemanticCache(similarity_threshold=0.9)
        assert cache.similarity_threshold == 0.9

    def test_default_redis_url_from_env(self):
        with patch.dict("os.environ", {"REDIS_URL": "redis://custom:6379/1"}):
            cache = SemanticCache()
            assert cache.redis_url == "redis://custom:6379/1"


# ---------------------------------------------------------------------------
# SemanticCache with fakeredis (async)
# ---------------------------------------------------------------------------

@pytest.fixture
def fakeredis_client():
    """Provide a fake async Redis client via fakeredis."""
    try:
        import fakeredis.aioredis
        return fakeredis.aioredis.FakeRedis
    except ImportError:
        pytest.skip("fakeredis not installed")


@pytest.fixture
def cache(fakeredis_client):
    """SemanticCache wired to fakeredis."""
    cache = SemanticCache(redis_url="redis://localhost:6379/0")
    # Patch _get_client to return a fakeredis instance with decode_responses
    # to match the real client's behavior (decode_responses=True).
    fake = fakeredis_client(decode_responses=True)
    cache._client = fake
    return cache


# ---------------------------------------------------------------------------
# lookup on empty cache
# ---------------------------------------------------------------------------

class TestLookupEmptyCache:
    @pytest.mark.asyncio
    async def test_returns_none_on_empty(self, cache):
        emb = _random_embedding()
        result = await cache.lookup("any query", emb)
        assert result is None


# ---------------------------------------------------------------------------
# store + lookup round-trip
# ---------------------------------------------------------------------------

class TestStoreLookupRoundTrip:
    @pytest.mark.asyncio
    async def test_roundtrip(self, cache):
        query = "What are the best beaches?"
        emb = _random_embedding()
        response = "Bãi Sao and Bãi Khem are popular choices."

        await cache.store(query, emb, response, ttl=3600)
        result = await cache.lookup(query, emb)
        assert result == response

    @pytest.mark.asyncio
    async def test_roundtrip_different_query(self, cache):
        q1 = "First query"
        q2 = "Second query"
        emb1 = _random_embedding(seed=42)
        emb2 = _random_embedding(seed=99)

        await cache.store(q1, emb1, "Response 1")
        await cache.store(q2, emb2, "Response 2")

        assert await cache.lookup(q1, emb1) == "Response 1"
        assert await cache.lookup(q2, emb2) == "Response 2"


# ---------------------------------------------------------------------------
# Cosine similarity threshold behavior
# ---------------------------------------------------------------------------

class TestSimilarityThreshold:
    @pytest.mark.asyncio
    async def test_similar_query_returns_hit(self, cache):
        query = "Best beaches in Phu Quoc"
        emb = _random_embedding()
        near_emb = _near_embedding(emb)  # similarity > 0.95

        await cache.store(query, emb, "Cached beach info")
        result = await cache.lookup("similar query about beaches", near_emb)
        assert result == "Cached beach info"

    @pytest.mark.asyncio
    async def test_dissimilar_query_returns_miss(self, cache):
        query = "Best beaches in Phu Quoc"
        emb = _random_embedding()
        far_emb = _far_embedding(emb)  # similarity < 0.95

        await cache.store(query, emb, "Cached beach info")
        result = await cache.lookup("totally different topic", far_emb)
        assert result is None


# ---------------------------------------------------------------------------
# Embedding dimension validation
# ---------------------------------------------------------------------------

class TestEmbeddingDimensionValidation:
    @pytest.mark.asyncio
    async def test_wrong_dimension_raises_valueerror(self, cache):
        bad_emb = [0.1] * 768  # wrong dimension
        with pytest.raises(ValueError, match="dimension mismatch"):
            await cache.store("query", bad_emb, "response")

    @pytest.mark.asyncio
    async def test_correct_dimension_passes(self, cache):
        good_emb = _random_embedding()
        # Should not raise
        await cache.store("query", good_emb, "response")


# ---------------------------------------------------------------------------
# Redis connection error handling
# ---------------------------------------------------------------------------

class TestRedisConnectionError:
    @pytest.mark.asyncio
    async def test_lookup_returns_none_on_connection_error(self):
        cache = SemanticCache(redis_url="redis://bad-host:9999/0")
        cache._client = None  # force reconnect attempt
        with patch.object(cache, "_get_client", return_value=None):
            result = await cache.lookup("query", _random_embedding())
            assert result is None

    @pytest.mark.asyncio
    async def test_store_silently_skips_on_connection_error(self):
        cache = SemanticCache(redis_url="redis://bad-host:9999/0")
        with patch.object(cache, "_get_client", return_value=None):
            # Should not raise
            await cache.store("query", _random_embedding(), "response")

    @pytest.mark.asyncio
    async def test_clear_returns_zero_on_connection_error(self):
        cache = SemanticCache(redis_url="redis://bad-host:9999/0")
        with patch.object(cache, "_get_client", return_value=None):
            count = await cache.clear()
            assert count == 0


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------

class TestClear:
    @pytest.mark.asyncio
    async def test_clear_returns_count(self, cache):
        emb = _random_embedding()
        await cache.store("q1", emb, "r1")
        await cache.store("q2", emb, "r2")
        count = await cache.clear()
        assert count == 2

    @pytest.mark.asyncio
    async def test_clear_on_empty(self, cache):
        count = await cache.clear()
        assert count == 0

    @pytest.mark.asyncio
    async def test_lookup_after_clear(self, cache):
        emb = _random_embedding()
        await cache.store("q1", emb, "r1")
        await cache.clear()
        assert await cache.lookup("q1", emb) is None


# ---------------------------------------------------------------------------
# TTL behaviour
# ---------------------------------------------------------------------------

class TestTTL:
    @pytest.mark.asyncio
    async def test_store_sets_ttl(self, cache):
        query = "ttl test"
        emb = _random_embedding()
        await cache.store(query, emb, "response", ttl=60)

        key = f"{SemanticCache.KEY_PREFIX}{_query_hash(query)}"
        ttl = await cache._client.ttl(key)
        assert 0 < ttl <= 60
