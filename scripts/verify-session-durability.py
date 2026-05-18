#!/usr/bin/env python3
"""Verify or explicitly re-scope agent session durability.

This diagnostic exercises the same checkpointer factory used by app startup.
With a working DATABASE_URL/Postgres backend it writes a synthetic turn, creates
an independent checkpointer, and verifies the turn survives that restart-like
reload. Without Postgres it proves memory mode is same-process only and exits
successfully with RESULT=rescope_required so milestone validation can make an
explicit pass/re-scope decision.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.services.agent_service import InMemoryAgentCheckpointer, create_agent_checkpointer  # noqa: E402

SESSION_PREFIX = "m004-s08-session-durability"
USER_MESSAGE = "synthetic durability user turn"
ASSISTANT_MESSAGE = "synthetic durability assistant turn"


def _has_saved_turn_in_order(history: list[dict[str, str]]) -> bool:
    """Return true when the synthetic user/assistant pair appears contiguously."""
    expected = [
        {"role": "user", "content": USER_MESSAGE},
        {"role": "assistant", "content": ASSISTANT_MESSAGE},
    ]
    return any(history[index : index + 2] == expected for index in range(max(len(history) - 1, 0)))


async def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    print("DATABASE_URL_STATUS=" + ("present" if database_url else "missing"))

    checkpointer, mode = await create_agent_checkpointer(database_url)
    print(f"CHECKPOINT_MODE={mode}")
    print(f"CHECKPOINTER_CLASS={type(checkpointer).__name__}")

    session_id = f"{SESSION_PREFIX}-{uuid4().hex}"
    await checkpointer.save_turn(session_id, USER_MESSAGE, ASSISTANT_MESSAGE)
    before_restart = await checkpointer.load_history(session_id)
    print(f"BEFORE_HISTORY_LEN={len(before_restart)}")

    if mode == "postgres":
        reloaded, reloaded_mode = await create_agent_checkpointer(database_url)
        reloaded_history = await reloaded.load_history(session_id)
        print(f"RESTART_HISTORY_LEN={len(reloaded_history)}")
        print(f"RELOADED_CHECKPOINT_MODE={reloaded_mode}")
        print(f"RELOADED_CHECKPOINTER_CLASS={type(reloaded).__name__}")

        if reloaded_mode == "postgres" and _has_saved_turn_in_order(reloaded_history):
            print("RESULT=durable_verified")
            return 0

        print("RESULT=durable_failed")
        print(
            "RATIONALE=postgres mode did not reload the saved synthetic user/assistant turn "
            "from a fresh checkpointer"
        )
        return 1

    fresh_memory = InMemoryAgentCheckpointer()
    after_restart = await fresh_memory.load_history(session_id)
    print(f"RESTART_HISTORY_LEN={len(after_restart)}")
    print("RELOADED_CHECKPOINT_MODE=memory")
    print(f"RELOADED_CHECKPOINTER_CLASS={type(fresh_memory).__name__}")
    print("RESULT=rescope_required")
    print("RATIONALE=session history is durable only when CHECKPOINT_MODE=postgres; memory mode is process-local")
    print("RERUN=export DATABASE_URL=<postgres dsn>; python3 scripts/verify-session-durability.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
