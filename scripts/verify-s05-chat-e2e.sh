#!/usr/bin/env bash
# verify-s05-chat-e2e.sh — Orchestrate S05 E2E chat test with server lifecycle.
# Starts dev server, waits for readiness, runs E2E test, cleans up.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"
E2E_TEST="$FRONTEND_DIR/tests/s05-chat-e2e.test.mjs"
MAX_WAIT=60
SERVER_PORT=3000

cleanup() {
  echo "[verify-s05-chat-e2e] Cleaning up dev server (PID=$SERVER_PID)..."
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    sleep 2
    kill -9 "$SERVER_PID" 2>/dev/null || true
  fi
  echo "[verify-s05-chat-e2e] Done."
}
trap cleanup EXIT

# Check if port is already in use
if lsof -i :$SERVER_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "[verify-s05-chat-e2e] ERROR: Port $SERVER_PORT is already in use. Please stop the existing server."
  exit 1
fi

echo "[verify-s05-chat-e2e] Starting Next.js dev server..."
cd "$FRONTEND_DIR"
bun run dev > /tmp/next-dev.log 2>&1 &
SERVER_PID=$!

echo "[verify-s05-chat-e2e] Waiting up to ${MAX_WAIT}s for server at http://localhost:$SERVER_PORT ..."
for i in $(seq 1 $MAX_WAIT); do
  if curl -sf --max-time 2 "http://localhost:$SERVER_PORT" > /dev/null 2>&1; then
    echo "[verify-s05-chat-e2e] Server is ready after ~${i}s"
    break
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "[verify-s05-chat-e2e] ERROR: Dev server died. Log:"
    tail -30 /tmp/next-dev.log || true
    exit 1
  fi
  echo -n "."
  sleep 1
done

if ! curl -sf --max-time 2 "http://localhost:$SERVER_PORT" > /dev/null 2>&1; then
  echo ""
  echo "[verify-s05-chat-e2e] ERROR: Server did not respond after ${MAX_WAIT}s. Log:"
  tail -30 /tmp/next-dev.log || true
  exit 1
fi

echo "[verify-s05-chat-e2e] Running S05 E2E chat test..."
cd "$REPO_ROOT"
node "$E2E_TEST"
TEST_EXIT=$?

echo "[verify-s05-chat-e2e] E2E test exited with code $TEST_EXIT"
exit $TEST_EXIT