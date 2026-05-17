#!/usr/bin/env bash
# verify-infra.sh — Docker Compose infrastructure verification
# Checks that all 4 services (postgres, redis, qdrant, backend) are
# running, healthy, and responding to connectivity probes.
#
# Usage: ./scripts/verify-infra.sh
# Exit: 0 if ALL checks pass; 1 if any check fails.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_DIR"

# ── Configuration (env vars with defaults) ─────────────────────────────
BACKEND_PORT="${HN_BACKEND_HOST_PORT:-48721}"
QDRANT_PORT="${HN_QDRANT_REST_HOST_PORT:-46333}"
COMPOSE="docker compose"

# ── Counters ───────────────────────────────────────────────────────────
PASS=0
FAIL=0
TOTAL=0

pass() { echo "  ✅ PASS: $1"; PASS=$((PASS + 1)); TOTAL=$((TOTAL + 1)); }
fail() { echo "  ❌ FAIL: $1"; FAIL=$((FAIL + 1)); TOTAL=$((TOTAL + 1)); }

echo "═══════════════════════════════════════════════════"
echo "  Infrastructure Verification — Ham Ninh AI"
echo "═══════════════════════════════════════════════════"

# ── Phase 1: Service Presence ─────────────────────────────────────────
echo ""
echo "--- Phase 1: Service Presence ---"

SERVICES=("postgres" "redis" "qdrant" "backend")

for svc in "${SERVICES[@]}"; do
    if $COMPOSE ps --format json 2>/dev/null \
        | python3 -c "
import json, sys
data = json.load(sys.stdin)
# docker compose ps --format json can return a list or a single object
services = data if isinstance(data, list) else [data]
found = [s for s in services if s.get('Service') == '${svc}']
sys.exit(0 if found else 1)
" 2>/dev/null; then
        pass "${svc} is running"
    else
        fail "${svc} is NOT running"
    fi
done

# ── Phase 2: Health Status ────────────────────────────────────────────
echo ""
echo "--- Phase 2: Health Status ---"

for svc in "${SERVICES[@]}"; do
    if $COMPOSE ps --format json 2>/dev/null \
        | python3 -c "
import json, sys
data = json.load(sys.stdin)
services = data if isinstance(data, list) else [data]
found = [s for s in services if s.get('Service') == '${svc}' and s.get('Health') == 'healthy']
sys.exit(0 if found else 1)
" 2>/dev/null; then
        pass "${svc} is healthy"
    else
        fail "${svc} is NOT healthy (or not running)"
    fi
done

# ── Phase 3: Connectivity Checks ──────────────────────────────────────
echo ""
echo "--- Phase 3: Connectivity Checks ---"

# Backend FastAPI docs
if curl -sf "http://localhost:${BACKEND_PORT}/docs" >/dev/null 2>&1; then
    pass "backend /docs (port ${BACKEND_PORT})"
else
    fail "backend /docs (port ${BACKEND_PORT})"
fi

# Qdrant healthz
if curl -sf "http://localhost:${QDRANT_PORT}/healthz" >/dev/null 2>&1; then
    pass "qdrant /healthz (port ${QDRANT_PORT})"
else
    fail "qdrant /healthz (port ${QDRANT_PORT})"
fi

# Redis PONG
if $COMPOSE exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; then
    pass "redis-cli ping"
else
    fail "redis-cli ping"
fi

# PostgreSQL pg_isready
if $COMPOSE exec -T postgres pg_isready -U ham_ninh 2>/dev/null; then
    pass "pg_isready (postgres)"
else
    fail "pg_isready (postgres)"
fi

# ── Summary ───────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  Results: ${PASS} passed, ${FAIL} failed (of ${TOTAL})"
echo "═══════════════════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
    echo "  ❌ Infrastructure verification FAILED"
    exit 1
fi

echo "  ✅ Infrastructure verification PASSED"
exit 0
