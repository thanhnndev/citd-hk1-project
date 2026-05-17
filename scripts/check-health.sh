#!/usr/bin/env bash
# check-health.sh — HTTP health verification for the backend service.
#
# Verifies /health (liveness) and /health/ready (readiness) endpoints
# return expected responses. Unlike verify-infra.sh (Docker-level checks),
# this script checks HTTP endpoints from the host perspective.
#
# Usage:
#   ./scripts/check-health.sh
#   BACKEND_URL=http://my-host:8000 ./scripts/check-health.sh
#
# Exit codes:
#   0 — all health checks passed
#   1 — one or more checks failed (or pre-flight error)

set -euo pipefail

# ── Pre-flight ──────────────────────────────────────────────
if ! command -v jq &>/dev/null; then
  echo "ERROR: jq is required but not installed."
  echo "Install it with:"
  echo "  macOS:  brew install jq"
  echo "  Ubuntu: sudo apt-get install -y jq"
  echo "  Alpine: apk add jq"
  exit 1
fi

if ! command -v curl &>/dev/null; then
  echo "ERROR: curl is required but not installed."
  exit 1
fi

# ── Configuration ───────────────────────────────────────────
BACKEND_URL="${BACKEND_URL:-http://localhost:48721}"

FAILURES=0

# ── Helpers ─────────────────────────────────────────────────

# check_endpoint URL PATH EXPECTED_STATUS EXPECTED_HTTP_CODE LABEL
# Makes an HTTP GET and verifies the JSON status field and HTTP code.
# Prints ✓ or ✗ with details.
check_endpoint() {
  local url="$1"
  local path="$2"
  local expected_status="$3"
  local expected_http_code="$4"
  local label="$5"

  local full_url="${url}${path}"
  local response
  response="$(curl -s -w '\n%{http_code}' --max-time 10 "${full_url}" 2>/dev/null)" || {
    echo "✗ ${label} (${path}) — connection failed (is the backend running?)"
    echo "  Tips: run \`make logs\` and \`make status\` to diagnose"
    FAILURES=$((FAILURES + 1))
    return
  }

  # Split response into body and HTTP code (last line is the code)
  local http_code
  http_code="$(echo "${response}" | tail -n1)"
  local body
  body="$(echo "${response}" | sed '$d')"

  if [ "${http_code}" != "${expected_http_code}" ]; then
    echo "✗ ${label} (${path}) — HTTP ${http_code} (expected ${expected_http_code})"
    echo "  Response: ${body}"
    echo "  Tips: run \`make logs\` and \`make status\` to diagnose"
    FAILURES=$((FAILURES + 1))
    return
  fi

  local actual_status
  actual_status="$(echo "${body}" | jq -r '.status' 2>/dev/null)" || {
    echo "✗ ${label} (${path}) — invalid JSON response"
    echo "  Response: ${body}"
    echo "  Tips: run \`make logs\` and \`make status\` to diagnose"
    FAILURES=$((FAILURES + 1))
    return
  }

  if [ "${actual_status}" != "${expected_status}" ]; then
    echo "✗ ${label} (${path}) — status '${actual_status}' (expected '${expected_status}')"
    echo "  Response: ${body}"
    echo "  Tips: run \`make logs\` and \`make status\` to diagnose"
    FAILURES=$((FAILURES + 1))
    return
  fi

  echo "✓ ${label} (${path}) — HTTP ${http_code}, status '${actual_status}'"
}

# ── Health Checks ───────────────────────────────────────────

echo "Checking backend health at ${BACKEND_URL} ..."
echo ""

# Liveness: GET /health → {"status":"ok"}, HTTP 200
check_endpoint "${BACKEND_URL}" "/health" "ok" "200" "Liveness"

# Readiness: GET /health/ready → {"status":"ready","services":{...}}, HTTP 200
# Then print per-service ✓/✗
check_readiness() {
  local full_url="${BACKEND_URL}/health/ready"
  local response
  response="$(curl -s -w '\n%{http_code}' --max-time 15 "${full_url}" 2>/dev/null)" || {
    echo "✗ Readiness (/health/ready) — connection failed"
    echo "  Tips: run \`make logs\` and \`make status\` to diagnose"
    FAILURES=$((FAILURES + 1))
    return
  }

  local http_code
  http_code="$(echo "${response}" | tail -n1)"
  local body
  body="$(echo "${response}" | sed '$d')"

  if [ "${http_code}" != "200" ]; then
    echo "✗ Readiness (/health/ready) — HTTP ${http_code} (expected 200)"
    echo "  Response: ${body}"
    echo "  Tips: run \`make logs\` and \`make status\` to diagnose"
    FAILURES=$((FAILURES + 1))
    return
  fi

  local actual_status
  actual_status="$(echo "${body}" | jq -r '.status' 2>/dev/null)" || {
    echo "✗ Readiness (/health/ready) — invalid JSON response"
    echo "  Response: ${body}"
    FAILURES=$((FAILURES + 1))
    return
  }

  if [ "${actual_status}" != "ready" ]; then
    echo "✗ Readiness (/health/ready) — status '${actual_status}' (expected 'ready')"
    echo "  Response: ${body}"
    # Still print per-service details even if overall status is degraded
    echo "  Per-service status:"
    echo "${body}" | jq -r '.services // {} | to_entries[] | "  \(.key): \(.value)"' 2>/dev/null
    FAILURES=$((FAILURES + 1))
    return
  fi

  echo "✓ Readiness (/health/ready) — HTTP ${http_code}, status '${actual_status}'"
  echo "  Per-service status:"
  # Print each service with ✓ or ✗
  local service_count
  service_count="$(echo "${body}" | jq '.services | length' 2>/dev/null)" || service_count=0
  if [ "${service_count}" -gt 0 ]; then
    local keys
    keys="$(echo "${body}" | jq -r '.services | keys[]' 2>/dev/null)"
    while IFS= read -r svc; do
      local svc_status
      svc_status="$(echo "${body}" | jq -r ".services[\"${svc}\"]" 2>/dev/null)"
      if [ "${svc_status}" = "ok" ]; then
        echo "  ✓ ${svc}: ${svc_status}"
      else
        echo "  ✗ ${svc}: ${svc_status}"
      fi
    done <<< "${keys}"
  fi
}

check_readiness

# ── Summary ─────────────────────────────────────────────────
echo ""
if [ "${FAILURES}" -eq 0 ]; then
  echo "All health checks passed."
  exit 0
else
  echo "${FAILURES} health check(s) failed."
  exit 1
fi
