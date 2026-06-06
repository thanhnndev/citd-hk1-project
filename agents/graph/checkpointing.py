"""Conversation history and follow-up context checkpointing."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import asyncpg
import structlog

from agents.graph.followup import FollowUpContext
from agents.services.place_recommendation_service import PLACE_RECOMMENDATION_INTENT

logger = structlog.get_logger(__name__)

class _NoopAsyncContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: Any) -> bool:
        return False


def _transaction(conn: Any) -> Any:
    tx = getattr(conn, "transaction", None)
    return tx() if callable(tx) else _NoopAsyncContext()


@dataclass
class InMemoryAgentCheckpointer:
    _store: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    _context_store: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def load_history(self, session_id: str) -> list[dict[str, str]]:
        return list(self._store.get(session_id, []))

    async def save_turn(self, session_id: str, user: str, assistant: str) -> None:
        history = self._store.setdefault(session_id, [])
        history.extend([{"role": "user", "content": user}, {"role": "assistant", "content": assistant}])
        del history[:-8]

    async def save_turn_with_context(self, session_id: str, user: str, assistant: str, ctx: FollowUpContext | None) -> None:
        await self.save_turn(session_id, user, assistant)
        if ctx is not None and ctx.is_populated:
            await self.save_context(session_id, ctx)

    async def load_context(self, session_id: str) -> FollowUpContext | None:
        raw = self._context_store.get(session_id)
        return FollowUpContext.from_dict(raw)

    async def save_context(self, session_id: str, ctx: FollowUpContext) -> None:
        self._context_store[session_id] = ctx.to_dict()


class PostgresAgentCheckpointer:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def create(cls, dsn: str) -> "PostgresAgentCheckpointer":
        pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5)
        checkpointer = cls(pool)
        try:
            await checkpointer.setup()
            await checkpointer.load_history("__agent_checkpoint_connectivity__")
        except Exception:
            await pool.close()
            raise
        return checkpointer

    async def setup(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """CREATE TABLE IF NOT EXISTS agent_sessions (
                    id TEXT PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    status TEXT NOT NULL DEFAULT 'active',
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                )"""
            )
            await conn.execute(
                """CREATE TABLE IF NOT EXISTS agent_session_messages (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
                    turn_index BIGINT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    intent TEXT,
                    latency_ms DOUBLE PRECISION,
                    fallback BOOLEAN,
                    provider_source TEXT,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )"""
            )
            # Upgrade older deployments that created the lightweight table first.
            await conn.execute("ALTER TABLE agent_session_messages ADD COLUMN IF NOT EXISTS turn_index BIGINT")
            await conn.execute("ALTER TABLE agent_session_messages ADD COLUMN IF NOT EXISTS intent TEXT")
            await conn.execute("ALTER TABLE agent_session_messages ADD COLUMN IF NOT EXISTS latency_ms DOUBLE PRECISION")
            await conn.execute("ALTER TABLE agent_session_messages ADD COLUMN IF NOT EXISTS fallback BOOLEAN")
            await conn.execute("ALTER TABLE agent_session_messages ADD COLUMN IF NOT EXISTS provider_source TEXT")
            await conn.execute("ALTER TABLE agent_session_messages ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb")
            await conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_agent_session_messages_session_turn
                ON agent_session_messages (session_id, turn_index, id)"""
            )
            await conn.execute(
                """CREATE TABLE IF NOT EXISTS agent_session_followup_context (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
                    source_message_id BIGINT REFERENCES agent_session_messages(id) ON DELETE SET NULL,
                    context_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )"""
            )
            await conn.execute("ALTER TABLE agent_session_followup_context ADD COLUMN IF NOT EXISTS source_message_id BIGINT")
            await conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_agent_session_followup_context_session
                ON agent_session_followup_context (session_id, id)"""
            )
            await conn.execute(
                """CREATE TABLE IF NOT EXISTS agent_place_memories (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
                    source_message_id BIGINT REFERENCES agent_session_messages(id) ON DELETE SET NULL,
                    place_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    aliases TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
                    rank INTEGER NOT NULL,
                    rating DOUBLE PRECISION,
                    price_level INTEGER,
                    reviews JSONB NOT NULL DEFAULT '[]'::jsonb,
                    opening_hours JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (session_id, place_id)
                )"""
            )
            await conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_agent_place_memories_session_name
                ON agent_place_memories (session_id, lower(display_name))"""
            )

    async def load_history(self, session_id: str) -> list[dict[str, str]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT role, content FROM (
                    SELECT id, role, content FROM agent_session_messages
                    WHERE session_id = $1 ORDER BY id DESC LIMIT 8
                ) recent ORDER BY id ASC""",
                session_id,
            )
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    async def save_turn(self, session_id: str, user: str, assistant: str) -> None:
        async with self._pool.acquire() as conn:
            if not hasattr(conn, "fetchval"):
                await conn.executemany(
                    """INSERT INTO agent_session_messages (session_id, role, content)
                    VALUES ($1, $2, $3)""",
                    [(session_id, "user", user), (session_id, "assistant", assistant)],
                )
                return
            async with _transaction(conn):
                await conn.execute(
                    """INSERT INTO agent_sessions (id) VALUES ($1)
                    ON CONFLICT (id) DO UPDATE SET updated_at = NOW()""",
                    session_id,
                )
                next_turn = await conn.fetchval(
                    "SELECT COALESCE(MAX(turn_index), 0) + 1 FROM agent_session_messages WHERE session_id = $1",
                    session_id,
                )
                await conn.executemany(
                    """INSERT INTO agent_session_messages (session_id, turn_index, role, content)
                    VALUES ($1, $2, $3, $4)""",
                    [(session_id, next_turn, "user", user), (session_id, next_turn, "assistant", assistant)],
                )

    async def save_turn_with_context(self, session_id: str, user: str, assistant: str, ctx: FollowUpContext | None) -> None:
        async with self._pool.acquire() as conn:
            async with _transaction(conn):
                await conn.execute(
                    """INSERT INTO agent_sessions (id) VALUES ($1)
                    ON CONFLICT (id) DO UPDATE SET updated_at = NOW()""",
                    session_id,
                )
                next_turn = await conn.fetchval(
                    "SELECT COALESCE(MAX(turn_index), 0) + 1 FROM agent_session_messages WHERE session_id = $1",
                    session_id,
                )
                await conn.execute(
                    """INSERT INTO agent_session_messages (session_id, turn_index, role, content)
                    VALUES ($1, $2, 'user', $3)""",
                    session_id, next_turn, user,
                )
                assistant_id = await conn.fetchval(
                    """INSERT INTO agent_session_messages
                    (session_id, turn_index, role, content, intent, fallback, provider_source)
                    VALUES ($1, $2, 'assistant', $3, $4, $5, $6)
                    RETURNING id""",
                    session_id,
                    next_turn,
                    assistant,
                    ctx.intent if ctx else None,
                    ctx.fallback if ctx else None,
                    ctx.provider_source if ctx else None,
                )
                if ctx is not None and ctx.is_populated:
                    await self._save_context_in_tx(conn, session_id, ctx, assistant_id)

    async def load_context(self, session_id: str) -> FollowUpContext | None:
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchval(
                    "SELECT context_json FROM agent_session_followup_context WHERE session_id = $1 ORDER BY id DESC LIMIT 1",
                    session_id,
                )
                memory_rows = await self._load_place_memory_rows(conn, session_id)
        except Exception:
            return None
        ctx: FollowUpContext | None = None
        if row is not None:
            try:
                data = json.loads(row) if isinstance(row, str) else row
                ctx = FollowUpContext.from_dict(data)
            except (json.JSONDecodeError, TypeError):
                ctx = None
        if memory_rows:
            ctx = self._context_from_place_memories(session_id, memory_rows, ctx)
        return ctx

    async def _load_place_memory_rows(self, conn: Any, session_id: str) -> list[Any]:
        fetch = getattr(conn, "fetch", None)
        if not callable(fetch):
            return []
        try:
            rows = await fetch(
                """SELECT place_id, display_name, rank, rating, price_level, reviews, opening_hours
                FROM agent_place_memories
                WHERE session_id = $1
                ORDER BY rank ASC, last_seen_at DESC
                LIMIT 10""",
                session_id,
            )
        except Exception:
            return []
        return [row for row in rows if isinstance(row, dict) and "place_id" in row and "display_name" in row]

    def _context_from_place_memories(self, session_id: str, rows: list[Any], base: FollowUpContext | None) -> FollowUpContext:
        ctx = base or FollowUpContext(session_id=session_id, intent=PLACE_RECOMMENDATION_INTENT)
        ctx.session_id = ctx.session_id or session_id
        ctx.intent = ctx.intent or PLACE_RECOMMENDATION_INTENT
        ctx.place_ids = [str(row.get("place_id") or "") for row in rows]
        ctx.place_display_names = [str(row.get("display_name") or row.get("place_id") or "") for row in rows]
        ctx.place_ratings = [float(row["rating"]) for row in rows if row.get("rating") is not None]
        ctx.place_price_levels = [int(row["price_level"]) for row in rows if row.get("price_level") is not None]
        ctx.place_reviews = [self._json_value(row.get("reviews"), []) for row in rows]
        ctx.place_hours = [self._json_value(row.get("opening_hours"), {}) for row in rows]
        return ctx

    def _json_value(self, value: Any, default: Any) -> Any:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return default
        return value if value is not None else default

    async def save_context(self, session_id: str, ctx: FollowUpContext) -> None:
        async with self._pool.acquire() as conn:
            async with _transaction(conn):
                await conn.execute(
                    """INSERT INTO agent_sessions (id) VALUES ($1)
                    ON CONFLICT (id) DO UPDATE SET updated_at = NOW()""",
                    session_id,
                )
                await self._save_context_in_tx(conn, session_id, ctx, None)

    async def _save_context_in_tx(self, conn: asyncpg.Connection, session_id: str, ctx: FollowUpContext, source_message_id: int | None) -> None:
        await conn.execute(
            """INSERT INTO agent_session_followup_context (session_id, source_message_id, context_json)
            VALUES ($1, $2, $3)""",
            session_id,
            source_message_id,
            json.dumps(ctx.to_dict(), ensure_ascii=False),
        )
        for rank, place_id in enumerate(ctx.place_ids):
            if not place_id:
                continue
            display_name = ctx.place_display_names[rank] if rank < len(ctx.place_display_names) else place_id
            aliases = [token for token in display_name.lower().split() if len(token) > 1]
            await conn.execute(
                """INSERT INTO agent_place_memories
                (session_id, source_message_id, place_id, display_name, aliases, rank, rating, price_level, reviews, opening_hours)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (session_id, place_id) DO UPDATE SET
                    source_message_id = EXCLUDED.source_message_id,
                    display_name = EXCLUDED.display_name,
                    aliases = EXCLUDED.aliases,
                    rank = EXCLUDED.rank,
                    rating = EXCLUDED.rating,
                    price_level = EXCLUDED.price_level,
                    reviews = EXCLUDED.reviews,
                    opening_hours = EXCLUDED.opening_hours,
                    last_seen_at = NOW()""",
                session_id,
                source_message_id,
                place_id,
                display_name,
                aliases,
                rank + 1,
                ctx.place_ratings[rank] if rank < len(ctx.place_ratings) else None,
                ctx.place_price_levels[rank] if rank < len(ctx.place_price_levels) else None,
                json.dumps(ctx.place_reviews[rank] if rank < len(ctx.place_reviews) else [], ensure_ascii=False),
                json.dumps(ctx.place_hours[rank] if rank < len(ctx.place_hours) else {}, ensure_ascii=False),
            )


async def create_agent_checkpointer(database_url: str | None = None) -> tuple[Any, str]:
    dsn = database_url or os.getenv("DATABASE_URL")
    if dsn:
        try:
            return await PostgresAgentCheckpointer.create(dsn), "postgres"
        except Exception as exc:
            logger.warning("agent.checkpoint_init_failed", checkpoint_mode="memory", reason=type(exc).__name__)
    return InMemoryAgentCheckpointer(), "memory"
