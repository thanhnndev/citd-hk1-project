"""Postgres-backed place cache for provider-failure fallback.

Stores normalized PlaceCandidate lists keyed by a deterministic hash of
PlaceSearchRequest fields (query, language_code, location_bias, radius).

On provider timeout/error/circuit-open:
- lookup() returns cached candidates (hit) or None (miss/stale).
- DB errors return miss with safe diagnostics — no exceptions propagate.

On successful provider response:
- upsert() persists sanitized candidates with TTL/staleness metadata.

Observability: emits structlog events place_cache.hit, place_cache.miss,
place_cache.stale, place_cache.write_ok, place_cache.write_failed — all
with cache_key hash, never raw query text or provider payloads.

Redaction: never logs or serializes GOOGLE_PLACES_API_KEY, DATABASE_URL
credentials, raw provider payloads, or unbounded user query text.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import asyncpg
import structlog

from app.models.places import PlaceCandidate, PlaceSearchRequest

logger = structlog.get_logger(__name__)

# Default TTL for cached place results (15 minutes)
DEFAULT_CACHE_TTL_SECONDS = 900

# Table creation DDL (idempotent — caller runs CREATE TABLE IF NOT EXISTS)
CREATE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS place_cache (
    cache_key       TEXT PRIMARY KEY,
    query_hash      TEXT NOT NULL,
    language_code   VARCHAR(5) NOT NULL,
    location_lat    DOUBLE PRECISION,
    location_lng    DOUBLE PRECISION,
    radius_meters   INTEGER,
    included_type   TEXT,
    candidates      JSONB NOT NULL,
    candidate_count INTEGER NOT NULL,
    cached_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    source          VARCHAR(40) NOT NULL DEFAULT 'goong_places'
)
"""

# Create index for stale-row sweeps
CREATE_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_place_cache_expires
    ON place_cache (expires_at)
"""


class CacheDiagnostics(dict):
    """Structured diagnostics returned by every cache operation."""

    @property
    def result(self) -> str:
        return self.get("result", "unknown")

    @property
    def cache_hit(self) -> bool:
        return self.result == "hit"

    @property
    def cache_stale(self) -> bool:
        return self.result == "stale"


class PlaceCacheProtocol(Protocol):
    """Protocol for place cache implementations."""

    async def lookup(
        self,
        request: PlaceSearchRequest,
        *,
        ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> tuple[list[PlaceCandidate] | None, CacheDiagnostics]: ...

    async def upsert(
        self,
        request: PlaceSearchRequest,
        candidates: list[PlaceCandidate],
        *,
        ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        source: str = "goong_places",
    ) -> CacheDiagnostics: ...

    async def ensure_table(self) -> None: ...

    async def close(self) -> None: ...


class PlaceCache:
    """Postgres-backed place cache with TTL and structured diagnostics.

    Args:
        pool: Existing asyncpg.Pool (preferred for connection sharing).
        dsn: Database URL for lazy pool creation (fallback).
        ttl_seconds: Default cache entry lifetime.
    """

    def __init__(
        self,
        *,
        pool: asyncpg.Pool | None = None,
        dsn: str | None = None,
        ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self._pool = pool
        self._dsn = dsn or os.getenv("DATABASE_URL")
        self._ttl_seconds = ttl_seconds
        self._owned_pool = False  # track if we created the pool

    @classmethod
    async def create(
        cls,
        dsn: str | None = None,
        *,
        pool: asyncpg.Pool | None = None,
        ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> "PlaceCache":
        """Factory: optionally create pool, ensure table, return instance."""
        cache = cls(pool=pool, dsn=dsn, ttl_seconds=ttl_seconds)
        if pool is None:
            dsn = cache._dsn
            if not dsn:
                logger.warning("place_cache.no_dsn", reason="DATABASE_URL not set; cache will be no-op")
                return cache
            cache._pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=3)
            cache._owned_pool = True
        await cache.ensure_table()
        return cache

    async def ensure_table(self) -> None:
        """Create the place_cache table and index if they don't exist."""
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(CREATE_TABLE_DDL)
            await conn.execute(CREATE_INDEX_DDL)

    # ------------------------------------------------------------------
    # Cache key derivation
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(request: PlaceSearchRequest) -> str:
        """Deterministic cache key from normalized request fields.

        Includes query (trimmed, whitespace-collapsed, lowercased for stability),
        language, location bias, and radius. Excludes max_result_count so that
        different page sizes share the same cached candidate pool.
        """
        import re
        query_normalized = re.sub(r"\s+", " ", request.query.strip().lower())
        query_hash = hashlib.sha256(query_normalized.encode("utf-8")).hexdigest()[:16]
        loc = request.location_bias
        key_parts = [
            query_hash,
            request.language_code,
            f"{loc.lat:.6f}",
            f"{loc.lng:.6f}",
            str(request.radius_meters),
            request.included_type or "any",
            "strict" if request.strict_type_filtering else "broad",
        ]
        return ":".join(key_parts)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    async def lookup(
        self,
        request: PlaceSearchRequest,
        *,
        ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> tuple[list[PlaceCandidate] | None, CacheDiagnostics]:
        """Look up cached candidates for a given search request.

        Returns:
            (candidates, diagnostics) where diagnostics.result is one of:
            - "hit": valid, non-expired cache entry found
            - "miss": no entry found
            - "stale": entry exists but is expired
            - "error": DB error occurred (candidates always None)
        """
        cache_key = self._cache_key(request)

        if self._pool is None:
            return None, CacheDiagnostics(
                result="miss",
                cache_key=cache_key[:8],
                reason="no_db_connection",
            )

        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT candidates, cached_at, expires_at, source "
                    "FROM place_cache WHERE cache_key = $1",
                    cache_key,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "place_cache.error",
                cache_key=cache_key[:8],
                error_type=type(exc).__name__,
                reason="lookup_failed",
            )
            return None, CacheDiagnostics(
                result="error",
                cache_key=cache_key[:8],
                error_type=type(exc).__name__,
            )

        if row is None:
            logger.info("place_cache.miss", cache_key=cache_key[:8])
            return None, CacheDiagnostics(
                result="miss",
                cache_key=cache_key[:8],
            )

        now = datetime.now(UTC)
        expires_at = row["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        if now > expires_at:
            # Stale entry — return candidates anyway so the service can serve
            # degraded results with a staleness warning.
            cached_at = row["cached_at"]
            staleness_seconds = (now - expires_at).total_seconds()
            try:
                raw_candidates = row["candidates"]
                if isinstance(raw_candidates, str):
                    raw_candidates = json.loads(raw_candidates)
                candidates = [
                    PlaceCandidate.model_validate(c)
                    for c in raw_candidates
                    if isinstance(c, dict)
                ]
            except Exception:  # noqa: BLE001
                logger.warning(
                    "place_cache.malformed_stale",
                    cache_key=cache_key[:8],
                    reason="invalid_json",
                )
                return None, CacheDiagnostics(
                    result="stale",
                    cache_key=cache_key[:8],
                    reason="malformed_cache_data",
                    cached_at=cached_at,
                    expires_at=expires_at,
                    staleness_seconds=round(staleness_seconds, 1),
                )

            if not candidates:
                return None, CacheDiagnostics(
                    result="stale",
                    cache_key=cache_key[:8],
                    reason="empty_candidates",
                    cached_at=cached_at,
                    expires_at=expires_at,
                    staleness_seconds=round(staleness_seconds, 1),
                )

            logger.info(
                "place_cache.stale",
                cache_key=cache_key[:8],
                candidate_count=len(candidates),
                staleness_seconds=round(staleness_seconds, 1),
            )
            return candidates, CacheDiagnostics(
                result="stale",
                cache_key=cache_key[:8],
                candidate_count=len(candidates),
                cached_at=cached_at,
                expires_at=expires_at,
                staleness_seconds=round(staleness_seconds, 1),
                source=row.get("source", "unknown"),
            )

        # Parse candidates from JSONB
        try:
            raw_candidates = row["candidates"]
            if isinstance(raw_candidates, str):
                raw_candidates = json.loads(raw_candidates)
            candidates = [
                PlaceCandidate.model_validate(c)
                for c in raw_candidates
                if isinstance(c, dict)
            ]
        except Exception:  # noqa: BLE001
            # Malformed cached data — treat as miss
            logger.warning(
                "place_cache.malformed",
                cache_key=cache_key[:8],
                reason="invalid_json",
            )
            return None, CacheDiagnostics(
                result="miss",
                cache_key=cache_key[:8],
                reason="malformed_cache_data",
            )

        if not candidates:
            return None, CacheDiagnostics(
                result="miss",
                cache_key=cache_key[:8],
                reason="empty_candidates",
            )

        logger.info(
            "place_cache.hit",
            cache_key=cache_key[:8],
            candidate_count=len(candidates),
            source=row.get("source", "unknown"),
        )
        return candidates, CacheDiagnostics(
            result="hit",
            cache_key=cache_key[:8],
            candidate_count=len(candidates),
            cached_at=row["cached_at"],
            source=row.get("source", "unknown"),
        )

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    async def upsert(
        self,
        request: PlaceSearchRequest,
        candidates: list[PlaceCandidate],
        *,
        ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        source: str = "goong_places",
    ) -> CacheDiagnostics:
        """Persist candidates for a given search request.

        Uses INSERT ... ON CONFLICT (cache_key) DO UPDATE for idempotent
        upsert semantics. Candidates are serialized as sanitized JSONB
        — no raw provider payloads or API keys.

        Returns:
            Diagnostics with result "write_ok" or "write_failed".
        """
        cache_key = self._cache_key(request)

        if self._pool is None:
            logger.warning(
                "place_cache.write_failed",
                cache_key=cache_key[:8],
                reason="no_db_connection",
            )
            return CacheDiagnostics(
                result="write_failed",
                cache_key=cache_key[:8],
                reason="no_db_connection",
            )

        if not candidates:
            return CacheDiagnostics(
                result="write_failed",
                cache_key=cache_key[:8],
                reason="empty_candidates",
            )

        # Sanitize: serialize only the model-dict representation (no secrets)
        sanitized = [c.model_dump(mode="json") for c in candidates]
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO place_cache (
                        cache_key, query_hash, language_code,
                        location_lat, location_lng, radius_meters,
                        included_type, candidates, candidate_count,
                        cached_at, expires_at, source
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    ON CONFLICT (cache_key) DO UPDATE SET
                        candidates      = EXCLUDED.candidates,
                        candidate_count = EXCLUDED.candidate_count,
                        cached_at       = EXCLUDED.cached_at,
                        expires_at      = EXCLUDED.expires_at,
                        source          = EXCLUDED.source
                    """,
                    cache_key,
                    hashlib.sha256(request.query.strip().lower().encode("utf-8")).hexdigest()[:16],
                    request.language_code,
                    request.location_bias.lat,
                    request.location_bias.lng,
                    request.radius_meters,
                    request.included_type,
                    json.dumps(sanitized),
                    len(candidates),
                    now,
                    expires_at,
                    source,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "place_cache.write_failed",
                cache_key=cache_key[:8],
                error_type=type(exc).__name__,
                reason="upsert_failed",
            )
            return CacheDiagnostics(
                result="write_failed",
                cache_key=cache_key[:8],
                error_type=type(exc).__name__,
            )

        logger.info(
            "place_cache.write_ok",
            cache_key=cache_key[:8],
            candidate_count=len(candidates),
            ttl_seconds=ttl_seconds,
        )
        return CacheDiagnostics(
            result="write_ok",
            cache_key=cache_key[:8],
            candidate_count=len(candidates),
            ttl_seconds=ttl_seconds,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the owned pool if we created it."""
        if self._owned_pool and self._pool is not None:
            await self._pool.close()
            self._owned_pool = False
