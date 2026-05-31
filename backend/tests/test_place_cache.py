"""Tests for the Postgres-backed place cache.

Uses a fake asyncpg pool/connection to verify:
- Table creation SQL
- Upsert of valid PlaceCandidate lists
- Lookup hit / miss / stale behavior
- Malformed cached row handling
- DB error graceful degradation (no exceptions propagate)
- Cache key determinism
- Secret redaction (no API keys or raw payloads in stored data)
- Negative inputs (invalid query/language/radius)
- Empty candidate rejection
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from app.models.places import LatLng, PlaceCandidate, PlaceSearchRequest
from agents.tools.place_cache import (
    CREATE_INDEX_DDL,
    CREATE_TABLE_DDL,
    DEFAULT_CACHE_TTL_SECONDS,
    CacheDiagnostics,
    PlaceCache,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(**overrides: Any) -> PlaceSearchRequest:
    """Create a PlaceSearchRequest with sensible defaults."""
    base = {
        "query": "nhà hàng hải sản Hàm Ninh",
        "language_code": "vi",
        "location_bias": LatLng(lat=10.1835208, lng=104.0496843),
        "radius_meters": 5000,
        "max_result_count": 10,
    }
    base.update(overrides)
    return PlaceSearchRequest(**base)


def _make_candidate(place_id: str = "place_001", **overrides: Any) -> PlaceCandidate:
    """Create a PlaceCandidate with sensible defaults."""
    base = {
        "place_id": place_id,
        "display_name": "Ham Ninh Seafood",
        "types": ["restaurant", "seafood"],
        "formatted_address": "Ham Ninh, Phu Quoc",
        "location": LatLng(lat=10.18, lng=104.05),
        "rating": 4.5,
    }
    base.update(overrides)
    return PlaceCandidate(**base)


class FakeConnection:
    """Minimal fake asyncpg connection for deterministic testing."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self.executed: list[tuple[str, tuple]] = []
        self.raise_on_execute: Exception | None = None
        self.raise_on_fetchrow: Exception | None = None
        self.fetchrow_result: dict | None | str = "__default__"

    async def execute(self, sql: str, *args: Any) -> str:
        self.executed.append((sql, args))
        if self.raise_on_execute:
            raise self.raise_on_execute
        if args and sql.strip().upper().startswith("INSERT"):
            cache_key = args[0]
            self._store[cache_key] = {
                "cache_key": cache_key,
                "candidates": args[7],  # JSON string
                "candidate_count": args[8],
                "cached_at": args[9],
                "expires_at": args[10],
                "source": args[11],
            }
        return "OK"

    async def fetchrow(self, sql: str, *args: Any) -> dict | None:
        self.executed.append((sql, args))
        if self.raise_on_fetchrow:
            raise self.raise_on_fetchrow
        if self.fetchrow_result == "__default__":
            cache_key = args[0] if args else None
            row = self._store.get(cache_key)
            if row is None:
                return None
            return {
                "candidates": json.loads(row["candidates"]),
                "cached_at": row["cached_at"],
                "expires_at": row["expires_at"],
                "source": row.get("source", "goong_places"),
            }
        return self.fetchrow_result


class FakePool:
    """Minimal fake asyncpg pool."""

    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection

    def acquire(self) -> Any:
        """Return a context manager yielding the fake connection."""
        class _Ctx:
            async def __aenter__(self2):
                return self._connection
            async def __aexit__(self2, *exc):
                pass
        return _Ctx()

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Cache key determinism tests
# ---------------------------------------------------------------------------

class TestCacheKey:
    """Verify deterministic cache key derivation."""

    def test_same_request_same_key(self):
        req1 = _make_request()
        req2 = _make_request()
        assert PlaceCache._cache_key(req1) == PlaceCache._cache_key(req2)

    def test_different_query_different_key(self):
        req1 = _make_request(query="seafood restaurant")
        req2 = _make_request(query="coffee shop")
        assert PlaceCache._cache_key(req1) != PlaceCache._cache_key(req2)

    def test_case_insensitive_query(self):
        req1 = _make_request(query="SEAFOOD RESTAURANT")
        req2 = _make_request(query="seafood restaurant")
        assert PlaceCache._cache_key(req1) == PlaceCache._cache_key(req2)

    def test_whitespace_normalized(self):
        req1 = _make_request(query="  seafood  restaurant  ")
        req2 = _make_request(query="seafood restaurant")
        assert PlaceCache._cache_key(req1) == PlaceCache._cache_key(req2)

    def test_different_language_different_key(self):
        req1 = _make_request(language_code="vi")
        req2 = _make_request(language_code="en")
        assert PlaceCache._cache_key(req1) != PlaceCache._cache_key(req2)

    def test_different_radius_different_key(self):
        req1 = _make_request(radius_meters=5000)
        req2 = _make_request(radius_meters=10000)
        assert PlaceCache._cache_key(req1) != PlaceCache._cache_key(req2)

    def test_different_location_different_key(self):
        req1 = _make_request(location_bias=LatLng(lat=10.0, lng=104.0))
        req2 = _make_request(location_bias=LatLng(lat=10.1, lng=104.1))
        assert PlaceCache._cache_key(req1) != PlaceCache._cache_key(req2)

    def test_max_result_count_does_not_affect_key(self):
        """Different page sizes should share the same cached candidate pool."""
        req1 = _make_request(max_result_count=5)
        req2 = _make_request(max_result_count=15)
        assert PlaceCache._cache_key(req1) == PlaceCache._cache_key(req2)


# ---------------------------------------------------------------------------
# Table creation tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestTableCreation:
    """Verify table and index creation SQL."""

    async def test_ensure_table_runs_create_ddl(self):
        conn = FakeConnection()
        pool = FakePool(conn)
        cache = PlaceCache(pool=pool)

        await cache.ensure_table()

        executed_sql = " ".join(sql for sql, _ in conn.executed)
        assert "CREATE TABLE IF NOT EXISTS place_cache" in executed_sql
        assert "CREATE INDEX IF NOT EXISTS idx_place_cache_expires" in executed_sql

    async def test_ensure_table_no_op_without_pool(self):
        cache = PlaceCache(pool=None)
        await cache.ensure_table()  # should not raise


# ---------------------------------------------------------------------------
# Upsert tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestUpsert:
    """Verify candidate persistence via upsert."""

    async def test_upsert_valid_candidates(self):
        conn = FakeConnection()
        pool = FakePool(conn)
        cache = PlaceCache(pool=pool)
        request = _make_request()
        candidates = [_make_candidate("p1"), _make_candidate("p2")]

        result = await cache.upsert(request, candidates, ttl_seconds=900)

        assert result.result == "write_ok"
        assert result["candidate_count"] == 2
        # Verify SQL was executed with INSERT ... ON CONFLICT
        insert_sqls = [sql for sql, _ in conn.executed if "INSERT" in sql.upper()]
        assert len(insert_sqls) == 1
        assert "ON CONFLICT" in insert_sqls[0]

    async def test_upsert_stores_sanitized_json(self):
        """Stored data must be valid JSON of PlaceCandidate dicts."""
        conn = FakeConnection()
        pool = FakePool(conn)
        cache = PlaceCache(pool=pool)
        request = _make_request()
        candidates = [_make_candidate("p1", rating=4.8, types=["restaurant"])]

        await cache.upsert(request, candidates)

        # The candidates arg (index 7) should be valid JSON
        insert_args = conn.executed[-1][1]
        candidates_json = insert_args[7]
        parsed = json.loads(candidates_json)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["place_id"] == "p1"
        assert parsed[0]["rating"] == 4.8

    async def test_upsert_no_secrets_in_stored_data(self):
        """Stored data must not contain API keys or sensitive fields."""
        conn = FakeConnection()
        pool = FakePool(conn)
        cache = PlaceCache(pool=pool)
        request = _make_request()
        candidates = [_make_candidate()]

        await cache.upsert(request, candidates)

        insert_args = conn.executed[-1][1]
        all_args_str = json.dumps(insert_args, default=str)
        assert "GOOGLE_PLACES_API_KEY" not in all_args_str
        assert "DATABASE_URL" not in all_args_str
        assert "api_key" not in all_args_str.lower()
        assert "password" not in all_args_str.lower()

    async def test_upsert_empty_candidates_fails_gracefully(self):
        conn = FakeConnection()
        pool = FakePool(conn)
        cache = PlaceCache(pool=pool)
        request = _make_request()

        result = await cache.upsert(request, [], ttl_seconds=900)

        assert result.result == "write_failed"
        assert result["reason"] == "empty_candidates"

    async def test_upsert_no_db_connection(self):
        """Without a pool, upsert should return write_failed, not raise."""
        cache = PlaceCache(pool=None)
        request = _make_request()
        candidates = [_make_candidate()]

        result = await cache.upsert(request, candidates)

        assert result.result == "write_failed"
        assert result["reason"] == "no_db_connection"

    async def test_upsert_db_error_graceful(self):
        """DB errors during upsert should return write_failed, not raise."""
        conn = FakeConnection()
        conn.raise_on_execute = asyncpg.PostgresError("connection lost")
        pool = FakePool(conn)
        cache = PlaceCache(pool=pool)
        request = _make_request()
        candidates = [_make_candidate()]

        result = await cache.upsert(request, candidates)

        assert result.result == "write_failed"
        assert result["error_type"] == "PostgresError"

    async def test_upsert_idempotent(self):
        """Running upsert twice with same key should succeed both times."""
        conn = FakeConnection()
        pool = FakePool(conn)
        cache = PlaceCache(pool=pool)
        request = _make_request()
        candidates = [_make_candidate("p1")]

        r1 = await cache.upsert(request, candidates)
        r2 = await cache.upsert(request, candidates)

        assert r1.result == "write_ok"
        assert r2.result == "write_ok"


# ---------------------------------------------------------------------------
# Lookup tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestLookup:
    """Verify cache lookup behavior: hit, miss, stale, error."""

    async def test_lookup_miss(self):
        """Empty cache should return miss."""
        conn = FakeConnection()
        conn.fetchrow_result = None
        pool = FakePool(conn)
        cache = PlaceCache(pool=pool)
        request = _make_request()

        candidates, diag = await cache.lookup(request)

        assert candidates is None
        assert diag.result == "miss"

    async def test_lookup_hit(self):
        """Valid, non-expired entry should return candidates."""
        conn = FakeConnection()
        now = datetime.now(UTC)
        future = now + timedelta(seconds=900)
        conn._store["test:key"] = {
            "candidates": json.dumps([_make_candidate("p1").model_dump(mode="json")]),
            "cached_at": now,
            "expires_at": future,
            "source": "goong_places",
        }
        conn.fetchrow_result = "__default__"
        pool = FakePool(conn)
        cache = PlaceCache(pool=pool)
        request = _make_request()

        # Manually set the cache key so it matches the stored entry
        with patch.object(PlaceCache, "_cache_key", return_value="test:key"):
            candidates, diag = await cache.lookup(request)

        assert candidates is not None
        assert len(candidates) == 1
        assert candidates[0].place_id == "p1"
        assert diag.result == "hit"
        assert diag["candidate_count"] == 1
        assert diag["source"] == "goong_places"

    async def test_lookup_stale_entry(self):
        """Expired entry should return stale, not candidates."""
        conn = FakeConnection()
        past = datetime.now(UTC) - timedelta(hours=1)
        expired = datetime.now(UTC) - timedelta(minutes=30)
        conn._store["test:key"] = {
            "candidates": json.dumps([_make_candidate("p1").model_dump(mode="json")]),
            "cached_at": past,
            "expires_at": expired,
            "source": "goong_places",
        }
        pool = FakePool(conn)
        cache = PlaceCache(pool=pool)
        request = _make_request()

        with patch.object(PlaceCache, "_cache_key", return_value="test:key"):
            candidates, diag = await cache.lookup(request)

        assert candidates is None
        assert diag.result == "stale"

    async def test_lookup_malformed_json_treated_as_miss(self):
        """Corrupt JSONB should be treated as a miss, not raise."""
        conn = FakeConnection()
        now = datetime.now(UTC)
        future = now + timedelta(seconds=900)
        conn._store["test:key"] = {
            "candidates": "NOT VALID JSON{{{",
            "cached_at": now,
            "expires_at": future,
            "source": "goong_places",
        }
        # Override fetchrow to return the raw bad data
        async def bad_fetchrow(sql: str, *args: Any) -> dict:
            return {
                "candidates": "NOT VALID JSON{{{",
                "cached_at": now,
                "expires_at": future,
                "source": "goong_places",
            }

        conn.fetchrow = bad_fetchrow  # type: ignore
        pool = FakePool(conn)
        cache = PlaceCache(pool=pool)
        request = _make_request()

        with patch.object(PlaceCache, "_cache_key", return_value="test:key"):
            candidates, diag = await cache.lookup(request)

        assert candidates is None
        assert diag.result == "miss"
        assert diag["reason"] == "malformed_cache_data"

    async def test_lookup_malformed_candidate_list_treated_as_miss(self):
        """JSON array with non-dict items should be treated as miss."""
        conn = FakeConnection()
        now = datetime.now(UTC)
        future = now + timedelta(seconds=900)

        async def bad_candidates_fetchrow(sql: str, *args: Any) -> dict:
            return {
                "candidates": [42, "not a dict", None],
                "cached_at": now,
                "expires_at": future,
                "source": "goong_places",
            }

        conn.fetchrow = bad_candidates_fetchrow  # type: ignore
        pool = FakePool(conn)
        cache = PlaceCache(pool=pool)
        request = _make_request()

        with patch.object(PlaceCache, "_cache_key", return_value="test:key"):
            candidates, diag = await cache.lookup(request)

        assert candidates is None
        assert diag.result == "miss"
        assert diag["reason"] == "empty_candidates"

    async def test_lookup_no_db_connection(self):
        """Without a pool, lookup should return miss, not raise."""
        cache = PlaceCache(pool=None)
        request = _make_request()

        candidates, diag = await cache.lookup(request)

        assert candidates is None
        assert diag.result == "miss"
        assert diag["reason"] == "no_db_connection"

    async def test_lookup_db_error_graceful(self):
        """DB errors during lookup should return error, not raise."""
        conn = FakeConnection()
        conn.raise_on_fetchrow = asyncpg.PostgresError("connection lost")
        pool = FakePool(conn)
        cache = PlaceCache(pool=pool)
        request = _make_request()

        candidates, diag = await cache.lookup(request)

        assert candidates is None
        assert diag.result == "error"
        assert diag["error_type"] == "PostgresError"

    async def test_lookup_roundtrip(self):
        """Upsert then lookup should return the same candidates."""
        conn = FakeConnection()
        pool = FakePool(conn)
        cache = PlaceCache(pool=pool)
        request = _make_request()
        candidates = [
            _make_candidate("p1", display_name="Seafood Place 1"),
            _make_candidate("p2", display_name="Seafood Place 2"),
        ]

        # Upsert
        upsert_result = await cache.upsert(request, candidates, ttl_seconds=900)
        assert upsert_result.result == "write_ok"

        # Lookup (the FakeConnection stores the data keyed by cache_key)
        # We need to set up the fetchrow to return the stored data
        cache_key = PlaceCache._cache_key(request)
        conn.fetchrow_result = "__default__"

        lookup_candidates, diag = await cache.lookup(request)

        assert lookup_candidates is not None
        assert len(lookup_candidates) == 2
        assert lookup_candidates[0].place_id == "p1"
        assert lookup_candidates[1].place_id == "p2"
        assert diag.result == "hit"


# ---------------------------------------------------------------------------
# Diagnostics tests
# ---------------------------------------------------------------------------

class TestCacheDiagnostics:
    """Verify CacheDiagnostics properties."""

    def test_hit_property(self):
        diag = CacheDiagnostics(result="hit")
        assert diag.cache_hit is True
        assert diag.cache_stale is False

    def test_stale_property(self):
        diag = CacheDiagnostics(result="stale")
        assert diag.cache_hit is False
        assert diag.cache_stale is True

    def test_miss_property(self):
        diag = CacheDiagnostics(result="miss")
        assert diag.cache_hit is False
        assert diag.cache_stale is False

    def test_error_property(self):
        diag = CacheDiagnostics(result="error", error_type="TimeoutError")
        assert diag.cache_hit is False
        assert diag["error_type"] == "TimeoutError"


# ---------------------------------------------------------------------------
# Negative input tests
# ---------------------------------------------------------------------------

class TestNegativeInputs:
    """Verify invalid inputs are rejected at the request level."""

    def test_empty_query_rejected(self):
        with pytest.raises(Exception):
            PlaceSearchRequest(query="")

    def test_too_long_query_rejected(self):
        with pytest.raises(Exception):
            PlaceSearchRequest(query="x" * 200)

    def test_invalid_language_rejected(self):
        with pytest.raises(Exception):
            PlaceSearchRequest(query="test", language_code="fr")

    def test_zero_radius_rejected(self):
        with pytest.raises(Exception):
            PlaceSearchRequest(query="test", radius_meters=0)

    def test_negative_radius_rejected(self):
        with pytest.raises(Exception):
            PlaceSearchRequest(query="test", radius_meters=-100)

    def test_too_large_radius_rejected(self):
        with pytest.raises(Exception):
            PlaceSearchRequest(query="test", radius_meters=100_000)


# ---------------------------------------------------------------------------
# Close / lifecycle tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestLifecycle:
    """Verify pool lifecycle management."""

    async def test_close_owned_pool(self):
        """When PlaceCache creates its own pool, close() should shut it down."""
        mock_pool = AsyncMock()
        cache = PlaceCache(pool=mock_pool)
        cache._owned_pool = True

        await cache.close()

        mock_pool.close.assert_called_once()
        assert cache._owned_pool is False

    async def test_close_non_owned_pool_is_noop(self):
        """When pool was injected, close() should not shut it down."""
        mock_pool = AsyncMock()
        cache = PlaceCache(pool=mock_pool)
        cache._owned_pool = False

        await cache.close()

        mock_pool.close.assert_not_called()

    async def test_close_without_pool_is_noop(self):
        cache = PlaceCache(pool=None)
        await cache.close()  # should not raise
