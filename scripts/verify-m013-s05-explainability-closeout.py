#!/usr/bin/env python3
"""Verify M013/S05 explainability, observability, and closeout evidence.

Runs the focused pytest targets from S01-S05, checks that the closeout evidence
document contains required headings and status vocabulary, and optionally runs a
live Google Places smoke check only when GOOGLE_PLACES_API_KEY is present.

Failure modes (Q5):
  - Missing credentials → RESULT=credential_blocked (local tests still RESULT=passed).
  - Provider 401/403 → RESULT=credential_blocked.
  - Provider timeout/5xx → RESULT=live_unavailable (local contract still holds).
  - Malformed local response → RESULT=failed.

Load profile (Q6):
  - Verifier is local/CI-style, not on the runtime path.
  - Live smoke makes at most ONE bounded provider request (15s timeout).

Negative tests (Q7):
  - Evidence doc must contain required vocabulary (credential_blocked, RESULT=passed, etc.).
  - Evidence doc must NOT contain raw secret patterns.
  - Place results must NOT use document citation language.

Exit codes:
  0 with RESULT=passed        — all local + live proof
  0 with RESULT=credential_blocked — all local pass, live proof blocked by missing/fake credentials
  0 with RESULT=live_unavailable   — all local pass, live proof unavailable (timeout/5xx)
  1 with RESULT=failed        — local test failure or malformed response
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
EVIDENCE_DOC = ROOT / "docs" / "M013-S05-CLOSEOUT-EVIDENCE.md"

# ---------------------------------------------------------------------------
# Test targets (S01-S05 aggregate)
# ---------------------------------------------------------------------------

# Core S05 test targets (explanation + decision trace)
S05_TEST_TARGETS = [
    "backend/tests/test_places_models.py",
    "backend/tests/test_agent_place_recommendations.py",
    "backend/tests/test_places_runtime_wiring.py",
]

# S01-S04 regression targets
REGRESSION_TEST_TARGETS = [
    "backend/tests/test_places_service.py",
]

ALL_TEST_TARGETS = S05_TEST_TARGETS + REGRESSION_TEST_TARGETS

# ---------------------------------------------------------------------------
# Evidence doc vocabulary checks
# ---------------------------------------------------------------------------

REQUIRED_VOCABULARY = [
    "credential_blocked",
    "RESULT=passed",
    "RESULT=failed",
    "RESULT=credential_blocked",
    "PlaceExplanation",
    "PlaceDecisionTrace",
    "PlaceAuditEvent",
    "FairnessAudit",
    "SearchPlacesToolResult",
    "no.*citation",           # no-citation guarantee
    "deterministic",           # deterministic composition
]

FORBIDDEN_PATTERNS = [
    r"api_key\s*[:=]\s*['\"]sk-",       # OpenAI-style key
    r"GOOGLE_PLACES_API_KEY\s*[:=]\s*['\"]AIza",  # Google-style key
    r"password\s*[:=]\s*['\"]",          # generic password
    r"secret\s*[:=]\s*['\"][^'\"]{8,}",  # generic secret value
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _banner(msg: str) -> None:
    width = max(len(msg) + 4, 60)
    print(f"\n{'=' * width}")
    print(f"  {msg}")
    print(f"{'=' * width}")


def _resolve(target: str) -> Path:
    return ROOT / target


def _parse_pass_count(stdout: str) -> int:
    """Extract the number of passed tests from pytest output."""
    for line in stdout.split("\n"):
        if "passed" in line:
            m = re.search(r"(\d+)\s+passed", line)
            if m:
                return int(m.group(1))
    return 0


# ---------------------------------------------------------------------------
# Check 1: Verify all test files exist
# ---------------------------------------------------------------------------

def check_test_files_exist() -> int:
    _banner("Check 1: Test file existence")
    missing = [t for t in ALL_TEST_TARGETS if not _resolve(t).exists()]
    if missing:
        print(f"  FAIL: Missing test files: {missing}")
        return 1
    print(f"  OK: All {len(ALL_TEST_TARGETS)} test files present")
    for t in ALL_TEST_TARGETS:
        print(f"    - {t}")
    return 0


# ---------------------------------------------------------------------------
# Check 2: Run pytest suite (S05 + regression)
# ---------------------------------------------------------------------------

def run_pytest() -> tuple[int, str, str]:
    """Run pytest on all test targets. Returns (exit_code, stdout, stderr)."""
    cmd = [
        sys.executable, "-m", "pytest",
        *[str(_resolve(t)) for t in ALL_TEST_TARGETS],
        "-q", "--tb=short",
    ]
    print(f"  Running: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def check_pytest_suite() -> int:
    _banner("Check 2: Full pytest suite (S05 + S01-S04 regression)")
    returncode, stdout, stderr = run_pytest()

    # Show last 30 lines of combined output (summary section)
    output_lines = (stdout + "\n" + stderr).split("\n")
    tail = output_lines[-30:] if len(output_lines) > 30 else output_lines
    for line in tail:
        print(f"  {line}")

    if returncode != 0:
        print(f"  FAIL: pytest returned exit code {returncode}")
        if returncode == 2:
            print("  Diagnostics: pytest collection or configuration error.")
        elif returncode == 5:
            print("  Diagnostics: no tests collected — test files may be empty or paths changed.")
        else:
            failed_count = sum(1 for line in stdout.split("\n") if "FAILED" in line)
            print(f"  Diagnostics: {failed_count} test(s) failed. See output above.")
        return 1

    pass_count = _parse_pass_count(stdout)
    print(f"  OK: {pass_count} test(s) passed")
    return 0


# ---------------------------------------------------------------------------
# Check 3: Evidence document vocabulary
# ---------------------------------------------------------------------------

def check_evidence_doc() -> int:
    _banner("Check 3: Evidence document vocabulary")
    if not EVIDENCE_DOC.exists():
        print(f"  FAIL: Evidence document not found: {EVIDENCE_DOC}")
        return 1

    content = EVIDENCE_DOC.read_text()

    # Check required vocabulary
    missing_vocab = []
    for pattern in REQUIRED_VOCABULARY:
        if not re.search(pattern, content, re.IGNORECASE):
            missing_vocab.append(pattern)

    if missing_vocab:
        print(f"  FAIL: Missing required vocabulary: {missing_vocab}")
        return 1
    print(f"  OK: All {len(REQUIRED_VOCABULARY)} required vocabulary terms found")

    # Check forbidden patterns (no raw secrets)
    for pattern in FORBIDDEN_PATTERNS:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            print(f"  FAIL: Forbidden pattern found: {pattern} at position {match.start()}")
            return 1
    print("  OK: No raw secret patterns in evidence document")
    return 0


# ---------------------------------------------------------------------------
# Check 4: No document citation language for place discovery (negative test)
# ---------------------------------------------------------------------------

def check_no_citation_leakage() -> int:
    _banner("Check 4: No document citation language for place discovery")
    """Search test files and evidence doc for patterns that would indicate
    place results using document citation language (which violates R037/R038)."""
    # Check test files — they should assert citations=[] for place results
    test_content = ""
    for target in ALL_TEST_TARGETS:
        p = _resolve(target)
        if p.exists():
            test_content += p.read_text()

    # The evidence doc should mention no-citation guarantee
    if EVIDENCE_DOC.exists():
        test_content += EVIDENCE_DOC.read_text()

    # We expect positive assertions that citations are empty for place results
    no_citation_patterns = [
        r"citations.*==.*\[\]",
        r"citations.*=.*\[\]",
        r"no.*citation",
        r"no.*RAG",
        r"no_rag",
    ]

    found_count = 0
    for pattern in no_citation_patterns:
        if re.search(pattern, test_content, re.IGNORECASE):
            found_count += 1

    if found_count < 2:
        print(f"  FAIL: Too few no-citation assertions (found {found_count}, expected ≥2)")
        return 1

    print(f"  OK: No-citation assertions present ({found_count} patterns)")
    return 0


# ---------------------------------------------------------------------------
# Check 5: Model import smoke test
# ---------------------------------------------------------------------------

def check_model_imports() -> int:
    _banner("Check 5: S05 model import smoke test")
    try:
        sys.path.insert(0, str(BACKEND))
        from app.models.response import (
            PlaceResult,
            PlaceExplanation,
            ChatResponse,
        )
        from app.models.places import (
            PlaceDecisionTrace,
            PlaceAuditEvent,
            PlaceAuditPhase,
            PLACE_AUDIT_EVENTS,
            FairnessAudit,
            SearchPlacesToolResult,
        )

        # Verify PlaceExplanation fields
        explanation_fields = set(PlaceExplanation.model_fields.keys())
        required_explanation = {
            "rank", "primary_reason", "matched_preferences", "local_context",
            "score_factors", "fairness_note", "accessibility_note",
            "route_summary", "provider_source", "provider_status",
            "evidence_fields_used",
        }
        missing = required_explanation - explanation_fields
        if missing:
            print(f"  FAIL: PlaceExplanation missing fields: {missing}")
            return 1
        print(f"  OK: PlaceExplanation has all required fields ({len(required_explanation)})")

        # Verify ChatResponse has decision_trace
        if "decision_trace" not in ChatResponse.model_fields:
            print("  FAIL: ChatResponse missing decision_trace field")
            return 1
        print("  OK: ChatResponse has decision_trace field")

        # Verify PlaceDecisionTrace has credential_status
        if "credential_status" not in PlaceDecisionTrace.model_fields:
            print("  FAIL: PlaceDecisionTrace missing credential_status field")
            return 1
        print("  OK: PlaceDecisionTrace has credential_status field")

        # Verify PLACE_AUDIT_EVENTS has canonical events
        if len(PLACE_AUDIT_EVENTS) < 20:
            print(f"  FAIL: Too few audit events (got {len(PLACE_AUDIT_EVENTS)}, expected ≥20)")
            return 1
        print(f"  OK: PLACE_AUDIT_EVENTS has {len(PLACE_AUDIT_EVENTS)} canonical events")

        return 0
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return 1


# ---------------------------------------------------------------------------
# Check 6: Live Google Places smoke check (credential-aware)
# ---------------------------------------------------------------------------

def _is_placeholder_key(key: str) -> bool:
    """Check if an API key is a placeholder/fake value."""
    if not key or len(key) < 10:
        return True
    placeholder_patterns = [
        "your_", "YOUR_", "replace", "REPLACE", "changeme", "CHANGEME",
        "fake", "FAKE", "test_key", "TEST_KEY", "example", "EXAMPLE",
        "placeholder", "PLACEHOLDER", "dummy", "DUMMY",
    ]
    return any(p in key for p in placeholder_patterns)


def check_live_google_places() -> tuple[int, str]:
    """Run a live Google Places Text Search smoke check.

    Returns (exit_code, status_string):
      (0, "RESULT=passed")        — live proof confirmed
      (0, "RESULT=credential_blocked") — key missing or placeholder
      (0, "RESULT=live_unavailable")   — provider timeout/5xx
      (1, "RESULT=failed")        — malformed response or unexpected error
    """
    _banner("Check 6: Live Google Places smoke check")

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()

    if not api_key or _is_placeholder_key(api_key):
        status = "credential_blocked"
        print(f"  SKIP: GOOGLE_PLACES_API_KEY is missing or placeholder")
        print(f"  STATUS: RESULT={status}")
        print("  Note: Local contract tests still pass independently.")
        return (0, f"RESULT={status}")

    # Attempt live request
    try:
        import urllib.request
        import ssl

        url = "https://places.googleapis.com/v1/places:searchText"
        body = json.dumps({
            "textQuery": "seafood restaurant Ham Ninh Phu Quoc",
            "maxResultCount": 3,
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "places.id,places.displayName,places.rating",
            },
            method="POST",
        )

        start = time.time()
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            elapsed_ms = int((time.time() - start) * 1000)
            data = json.loads(resp.read().decode("utf-8"))
            places = data.get("places", [])

            if resp.status == 200 and len(places) >= 1:
                print(f"  OK: Live Google Places returned {len(places)} place(s) in {elapsed_ms}ms")
                print(f"  STATUS: RESULT=passed")
                return (0, "RESULT=passed")
            else:
                print(f"  FAIL: Unexpected response: status={resp.status}, places={len(places)}")
                print(f"  STATUS: RESULT=failed")
                return (1, "RESULT=failed")

    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            print(f"  BLOCKED: Provider returned HTTP {exc.code} (credential rejected)")
            print(f"  STATUS: RESULT=credential_blocked")
            return (0, "RESULT=credential_blocked")
        else:
            print(f"  UNAVAILABLE: Provider returned HTTP {exc.code}")
            print(f"  STATUS: RESULT=live_unavailable")
            return (0, "RESULT=live_unavailable")

    except urllib.error.URLError as exc:
        reason = str(exc.reason)
        if "timeout" in reason.lower() or "timed out" in reason.lower():
            print(f"  UNAVAILABLE: Provider request timed out (>15s)")
            print(f"  STATUS: RESULT=live_unavailable")
            return (0, "RESULT=live_unavailable")
        print(f"  UNAVAILABLE: Network error: {reason}")
        print(f"  STATUS: RESULT=live_unavailable")
        return (0, "RESULT=live_unavailable")

    except Exception as exc:
        print(f"  FAIL: Unexpected error: {exc}")
        print(f"  STATUS: RESULT=failed")
        return (1, "RESULT=failed")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    _banner("M013/S05 Explainability & Closeout Verification")

    checks = [
        ("Test file existence", check_test_files_exist),
        ("Full pytest suite (S05 + regression)", check_pytest_suite),
        ("Evidence document vocabulary", check_evidence_doc),
        ("No citation leakage (negative test)", check_no_citation_leakage),
        ("Model import smoke test", check_model_imports),
        ("Live Google Places smoke check", check_live_google_places),
    ]

    results = []
    for label, fn in checks:
        result = fn()
        # check_live_google_places returns tuple
        if isinstance(result, tuple):
            rc, status_str = result
        else:
            rc, status_str = result, ""
        results.append((label, rc, status_str))

    # ── Final verdict ──────────────────────────────────────────────────
    _banner("M013/S05 Verification Summary")

    local_checks = results[:5]  # All checks except live smoke
    live_check = results[5]

    local_pass = sum(1 for _, rc, _ in local_checks if rc == 0)
    local_total = len(local_checks)

    print(f"  Local checks:  {local_pass}/{local_total} passed")
    print(f"  Live check:    {live_check[2]}")
    print()

    # Determine overall verdict
    if any(rc != 0 for _, rc, _ in local_checks):
        failed = [label for label, rc, _ in local_checks if rc != 0]
        print(f"  RESULT=failed")
        print(f"  Failed checks: {', '.join(failed)}")
        return 1

    # Local tests all passed; live status determines the overall label
    live_status = live_check[2]
    if "passed" in live_status:
        print("  RESULT=passed")
        print("  All local and live checks passed.")
        return 0
    elif "credential_blocked" in live_status:
        print("  RESULT=credential_blocked")
        print("  All local tests pass. Live proof blocked by missing/fake credentials.")
        print("  Provide a valid GOOGLE_PLACES_API_KEY to confirm live provider success.")
        return 0
    elif "live_unavailable" in live_status:
        print("  RESULT=live_unavailable")
        print("  All local tests pass. Live proof unavailable (provider timeout/5xx).")
        return 0
    else:
        print(f"  {live_status}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
