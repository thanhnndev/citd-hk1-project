#!/usr/bin/env python3
"""Verify or explicitly re-scope agent session durability.

This diagnostic exercises the same checkpointer factory used by app startup.
With a working DATABASE_URL/Postgres LangGraph checkpoint backend it reports that
restart durability can be tested. Without it, it proves the current memory mode
is same-process only and exits successfully with RESULT=rescope_required so
milestone validation can make an explicit pass/re-scope decision.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.services.agent_service import InMemoryAgentCheckpointer, create_agent_checkpointer  # noqa: E402


async def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    print("DATABASE_URL_STATUS=" + ("present" if database_url else "missing"))

    checkpointer, mode = await create_agent_checkpointer(database_url)
    print(f"CHECKPOINT_MODE={mode}")
    print(f"CHECKPOINTER_CLASS={type(checkpointer).__name__}")

    if mode == "postgres":
        session_id = "m004-s06-session-durability"
        await checkpointer.save_turn(session_id, "first turn", "assistant turn")
        reloaded, reloaded_mode = await create_agent_checkpointer(database_url)
        history = await reloaded.load_history(session_id)
        print(f"RESTART_HISTORY_LEN={len(history)}")
        print(f"RESTART_MODE={reloaded_mode}")
        if len(history) >= 2:
            print("RESULT=durable_verified")
            return 0
        print("RESULT=durable_failed")
        return 1

    first = InMemoryAgentCheckpointer()
    await first.save_turn("m004-s06-session-durability", "first turn", "assistant turn")
    before_restart = await first.load_history("m004-s06-session-durability")
    after_restart = await InMemoryAgentCheckpointer().load_history("m004-s06-session-durability")
    print(f"MEMORY_BEFORE_RESTART_LEN={len(before_restart)}")
    print(f"MEMORY_AFTER_RESTART_LEN={len(after_restart)}")
    print("RESULT=rescope_required")
    print("RATIONALE=session history is durable only when CHECKPOINT_MODE=postgres; memory mode is process-local")
    print("RERUN=export DATABASE_URL=<postgres dsn>; python3 scripts/verify-session-durability.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
