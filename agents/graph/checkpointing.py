"""Conversation history and follow-up context checkpointing."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import asyncpg
import structlog

from agents.graph.followup import FollowUpContext

logger = structlog.get_logger(__name__)


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
                """CREATE TABLE IF NOT EXISTS agent_session_messages (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )"""
            )
            await conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_agent_session_messages_session_order
                ON agent_session_messages (session_id, id)"""
            )
            await conn.execute(
                """CREATE TABLE IF NOT EXISTS agent_session_followup_context (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    context_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )"""
            )
            await conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_agent_session_followup_context_session
                ON agent_session_followup_context (session_id, id)"""
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
            await conn.executemany(
                """INSERT INTO agent_session_messages (session_id, role, content)
                VALUES ($1, $2, $3)""",
                [(session_id, "user", user), (session_id, "assistant", assistant)],
            )

    async def load_context(self, session_id: str) -> FollowUpContext | None:
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchval(
                    "SELECT context_json FROM agent_session_followup_context WHERE session_id = $1 ORDER BY id DESC LIMIT 1",
                    session_id,
                )
        except Exception:
            return None
        if row is None:
            return None
        try:
            data = json.loads(row) if isinstance(row, str) else row
            return FollowUpContext.from_dict(data)
        except (json.JSONDecodeError, TypeError):
            return None

    async def save_context(self, session_id: str, ctx: FollowUpContext) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO agent_session_followup_context (session_id, context_json)
                VALUES ($1, $2)""",
                session_id,
                json.dumps(ctx.to_dict(), ensure_ascii=False),
            )


async def create_agent_checkpointer(database_url: str | None = None) -> tuple[Any, str]:
    dsn = database_url or os.getenv("DATABASE_URL")
    if dsn:
        try:
            return await PostgresAgentCheckpointer.create(dsn), "postgres"
        except Exception as exc:
            logger.warning("agent.checkpoint_init_failed", checkpoint_mode="memory", reason=type(exc).__name__)
    return InMemoryAgentCheckpointer(), "memory"
