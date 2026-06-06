#!/usr/bin/env python3
"""Verify M013/S04 social impact preferences and cultural context contract.

Runs focused model and agent recommendation tests for:
  - T01: Preference contract (budget, accessibility, user-location)
  - T02: Preferences wired through chat schema → service → filtering
  - T03: Ham Ninh cultural/community context on commercial suggestions

Also runs the S02 fairness regression subset so fairness balancing
remains intact after preference reranking.

Never requires GOOGLE_PLACES_API_KEY or network access.

Exits 0 with RESULT=passed when all checks pass.
Exits 1 with RESULT=failed and sanitized diagnostics on failure.

Slice verification targets:
  1. PlaceSearchRequest preference fields (budget, accessibility, user_location)
     with PriceLevel enum, computed properties, and input validation.
  2. Budget, accessibility, user-location preferences affect recommendation
     ordering/filtering through the full /chat search_places path.
  3. Commercial Ham Ninh suggestions include short cultural/community context
     (Vietnamese/English prefaces) without document citations.
  4. No invented place names, no document citations in place results.
  5. Fairness balancing (S02) ≥40% top-5 local target preserved after
     preference reranking.
  6. Runtime diagnostics: reasoning_log includes redacted preference flags,
     filtered_count, provider_status; no secrets/PII/exact GPS in logs.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

# ---------------------------------------------------------------------------
# Test targets
# ---------------------------------------------------------------------------

MODEL_TESTS = "backend/tests/test_places_models.py"
AGENT_TESTS = "backend/tests/test_agent_place_recommendations.py"
S04_CONTRACT_TESTS = "backend/tests/test_m013_s04_preferences_cultural_context.py"

# T01 keyword: preference contract tests in model file
T01_KEYWORDS = (
    "PriceLevel or ValidPreferences or EffectiveOrigin or "
    "NumericPrice or PreferenceSummary or InvalidPreferences or "
    "DefaultHamNinh or PreferenceSerialization"
)

# T02 keyword: preference wiring tests in agent file
T02_KEYWORDS = (
    "budget_filter or accessibility_preference or "
    "user_location_preference or preferences_change or "
    "invalid_budget or no_candidates_after or "
    "fairness_still_applies_after or "
    "no_rag_citations_introduced_by or backward_compat or "
    "agent_service_carries or malformed_tool_args or "
    "preference_diagnostics"
)

# T03 keyword: cultural context, safety, and diagnostic tests.
T03_KEYWORDS = (
    "commercial_ok_message or cultural_preface or "
    "non_commercial or empty_results_no_cultural or empty_results_no_cultural_preface or "
    "credentials_blocked_no_cultural or credentials_blocked_no_cultural_preface or "
    "upstream_error_no_cultural or upstream_error_no_cultural_preface or "
    "no_invented_place or no_document_citations or place_discovery_paths_return_empty_citations or "
    "unusual_punctuation or injection_like or malformed_display_name or minimal_display_name or "
    "missing_local_factor or none_local_factor or fairness_audit_present or "
    "cache_hit_status or reasoning_log_contains_preference_flags or is_commercial_query"
)

# S02 fairness regression subset
S02_FAIRNESS_KEYWORDS = (
    "fairness or Fairness or balance_fairness or fairness_audit or "
    "FairnessAudit or FairnessWarningType or top5_local"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _banner(msg: str) -> None:
    print(f"\n{'='*60}\n  {msg}\n{'='*60}")


def _resolve(target: str) -> Path:
    return ROOT / target


def check_model_imports() -> int:
    """Check 1: Verify preference contract types import cleanly."""
    _banner("Check 1: Preference contract model imports")
    try:
        sys.path.insert(0, str(BACKEND))
        from app.models.places import (
            HAM_NINH_CENTER,
            PlaceSearchRequest,
            PriceLevel,
        )
        from app.models.request import LatLng

        # Check PriceLevel enum values
        expected_levels = {"free", "inexpensive", "moderate", "expensive", "very_expensive"}
        actual_levels = {level.value for level in PriceLevel}
        if actual_levels != expected_levels:
            print(f"  FAIL: PriceLevel values mismatch. Expected {expected_levels}, got {actual_levels}")
            return 1
        print(f"  OK: PriceLevel enum has correct values: {sorted(actual_levels)}")

        # Check PlaceSearchRequest has preference fields
        required_fields = {"budget_filter", "wheelchair_accessible_preference", "user_location"}
        actual_fields = set(PlaceSearchRequest.model_fields.keys())
        missing = required_fields - actual_fields
        if missing:
            print(f"  FAIL: Missing PlaceSearchRequest fields: {missing}")
            return 1
        print(f"  OK: PlaceSearchRequest has preference fields: {sorted(required_fields)}")

        # Check HAM_NINH_CENTER default
        assert hasattr(HAM_NINH_CENTER, "lat"), "HAM_NINH_CENTER must have lat"
        assert hasattr(HAM_NINH_CENTER, "lng"), "HAM_NINH_CENTER must have lng"
        print(f"  OK: HAM_NINH_CENTER default bias present")
        return 0
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return 1


def check_pytest_suite(targets: list, label: str, keyword_filter: str = None) -> tuple:
    """Run a pytest suite. Returns (exit_code, pass_count).

    Verifies all test files exist first.
    """
    _banner(f"Check: Pytest {label}")

    # Verify all test files exist
    missing = [t for t in targets if not _resolve(t).exists()]
    if missing:
        print(f"  FAIL: Missing test files: {missing}")
        return (1, 0)

    cmd = [sys.executable, "-m", "pytest"]
    for t in targets:
        cmd.append(str(_resolve(t)))
    cmd.extend(["-q", "--tb=short"])
    if keyword_filter:
        cmd.extend(["-k", keyword_filter])

    print(f"  Running: {' '.join(cmd[:6])} ...")
    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    # Show last 20 lines of combined output
    output_lines = (stdout + "\n" + stderr).split("\n")
    tail = output_lines[-20:] if len(output_lines) > 20 else output_lines
    for line in tail:
        print(f"  {line}")

    if result.returncode != 0:
        print(f"  FAIL: pytest returned exit code {result.returncode}")
        if result.returncode == 2:
            print("  Diagnostics: pytest collection or configuration error.")
        elif result.returncode == 5:
            print("  Diagnostics: no tests collected — keyword may need updating.")
        else:
            failed_count = sum(1 for line in stdout.split("\n") if "FAILED" in line)
            print(f"  Diagnostics: {failed_count} test(s) failed. See output above.")
        return (1, 0)

    # Extract pass count
    pass_count = 0
    for line in stdout.split("\n"):
        if "passed" in line:
            m = re.search(r"(\d+)\s+passed", line)
            if m:
                pass_count = int(m.group(1))

    print(f"  OK: {pass_count} test(s) passed")
    return (0, pass_count)


def check_t01_preference_contract() -> tuple:
    """Check 2: T01 preference contract tests (budget, accessibility, user-location)."""
    return check_pytest_suite(
        [MODEL_TESTS],
        label="T01 preference contract (PriceLevel, validation, serialization)",
        keyword_filter=T01_KEYWORDS,
    )


def check_t02_preference_wiring() -> tuple:
    """Check 3: T02 preference wiring tests (budget, accessibility, user-location through chat)."""
    return check_pytest_suite(
        [AGENT_TESTS],
        label="T02 preference wiring (budget/accessibility/user_location through /chat)",
        keyword_filter=T02_KEYWORDS,
    )


def check_t03_cultural_context() -> tuple:
    """Check 4: T03 cultural context tests (Ham Ninh prefaces, no citations, no invented names)."""
    return check_pytest_suite(
        [AGENT_TESTS, S04_CONTRACT_TESTS],
        label="T03 cultural context (commercial prefaces, no citations, no invented names)",
        keyword_filter=T03_KEYWORDS,
    )


def check_s02_fairness_regression() -> tuple:
    """Check 5: S02 fairness regression — balancing preserved after preference rerank."""
    return check_pytest_suite(
        [AGENT_TESTS, MODEL_TESTS],
        label="S02 fairness regression (balancing preserved after preference rerank)",
        keyword_filter=S02_FAIRNESS_KEYWORDS,
    )


def main() -> int:
    checks = [
        ("Preference contract model imports", check_model_imports),
        ("T01: Preference contract tests", check_t01_preference_contract),
        ("T02: Preference wiring tests", check_t02_preference_wiring),
        ("T03: Cultural context tests", check_t03_cultural_context),
        ("S02: Fairness regression subset", check_s02_fairness_regression),
    ]

    results = []
    total_pass = 0
    for label, fn in checks:
        result = fn()
        if isinstance(result, tuple):
            rc, passed = result
        else:
            rc, passed = result, 0
        results.append((label, rc, passed))
        if rc == 0:
            total_pass += 1

    _banner("M013/S04 Preferences & Cultural Context Verification")
    print(f"  {total_pass}/{len(results)} checks passed")
    print()

    # Summarize promises verified
    print("  S04 promises verified:")
    if results[1][1] == 0:
        print(f"    ✅ T01: Preference contract ({results[1][2]} tests) — PriceLevel enum, validation, serialization")
    if results[2][1] == 0:
        print(f"    ✅ T02: Preference wiring ({results[2][2]} tests) — budget/accessibility/user_location through /chat")
    if results[3][1] == 0:
        print(f"    ✅ T03: Cultural context ({results[3][2]} tests) — commercial prefaces, no citations, no invented names")
    if results[4][1] == 0:
        print(f"    ✅ S02 regression: Fairness balancing preserved after preference rerank ({results[4][2]} tests)")
    print()

    if all(r[1] == 0 for r in results):
        print("  RESULT=passed")
        return 0

    print("  RESULT=failed")
    failed = [r[0] for r in results if r[1] != 0]
    print(f"  Failed checks: {', '.join(failed)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
