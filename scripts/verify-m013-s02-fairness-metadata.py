#!/usr/bin/env python3
"""Verify M013/S02 fairness and metadata coverage contract.

Runs the focused model/service tests from T01/T02 plus S01 deterministic
place regression targets. Reports a single RESULT=passed/failed closeout.

Never requires GOOGLE_PLACES_API_KEY or network access.

S02 promises verified:
  1. FairnessAudit model contract (candidate_count, result_count, top5_local_ratio,
     missing_local_factor_count, provider_status, warnings; extra='forbid').
  2. FairnessWarningType enum has all 5 standardized warning values.
  3. Fairness balancing achieves ≥40% top-5 local target when enough locals exist.
  4. ChatResponse carries fairness_audit with structured diagnostics.
  5. No secret leakage in serialized audit fields or reasoning_log.
  6. S01 deterministic /chat place output preserved (no regression): no citations,
     no RAG fallback, no LLM override, honest failure modes.

Exits 0 with RESULT=passed when all checks pass.
Exits 1 with RESULT=failed and sanitized diagnostics on failure.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

# T01/T02 fairness-focused test files
FAIRNESS_TEST_TARGETS = [
    "backend/tests/test_places_models.py",
    "backend/tests/test_agent_place_recommendations.py",
]

# S01 deterministic place contract test files (regression guard)
S01_TEST_TARGETS = [
    "backend/tests/test_places_service.py",
    "backend/tests/test_chat_api.py",
    "backend/tests/test_chat_endpoint.py",
]

# Keywords to filter fairness-specific tests in the fairness suite
FAIRNESS_KEYWORDS = "fairness or Fairness or balance_fairness or fairness_audit or FairnessAudit or FairnessWarningType or top5_local"


def _banner(msg: str) -> None:
    print(f"\n{'='*60}\n  {msg}\n{'='*60}")


def _resolve(target: str) -> Path:
    return ROOT / target


def check_model_imports() -> int:
    """Check 1: Verify FairnessAudit and FairnessWarningType import cleanly."""
    _banner("Check 1: FairnessAudit model imports")
    try:
        sys.path.insert(0, str(BACKEND))
        from app.models.places import FairnessAudit, FairnessWarningType
        from app.models.response import ChatResponse

        # Check required fields
        assert hasattr(FairnessAudit, "model_fields"), "FairnessAudit must be a Pydantic model"
        required_fields = {
            "candidate_count", "result_count", "top5_local_ratio",
            "missing_local_factor_count", "provider_status", "warnings",
        }
        actual = set(FairnessAudit.model_fields.keys())
        missing = required_fields - actual
        if missing:
            print(f"  FAIL: Missing FairnessAudit fields: {missing}")
            return 1
        print(f"  OK: All required fields present: {sorted(required_fields)}")

        # Check warning vocabulary
        expected_warnings = {
            "insufficient_local_candidates",
            "missing_local_factor_metadata",
            "provider_non_ok",
            "route_enrichment_fallback",
            "reranking_fallback",
        }
        actual_warnings = {w.value for w in FairnessWarningType}
        if actual_warnings != expected_warnings:
            print(f"  FAIL: Warning vocabulary mismatch. Expected {expected_warnings}, got {actual_warnings}")
            return 1
        print(f"  OK: All warning values present: {sorted(expected_warnings)}")

        # Check ChatResponse integration
        assert "fairness_audit" in ChatResponse.model_fields, "ChatResponse must have fairness_audit field"
        print("  OK: ChatResponse has fairness_audit field")
        return 0
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return 1


def check_secret_redaction() -> int:
    """Check 2: Verify serialized audit fields contain no secrets."""
    _banner("Check 2: Secret redaction in audit fields")
    try:
        sys.path.insert(0, str(BACKEND))
        from app.models.places import FairnessAudit

        audit = FairnessAudit(
            candidate_count=5, result_count=3, top5_local_ratio=0.6,
            provider_status="ok", warnings=["missing_local_factor_metadata"],
        )
        dump = audit.model_dump_json()
        for forbidden in ("api_key", "secret", "raw", "payload", "token"):
            if forbidden in dump.lower():
                print(f"  FAIL: Secret leakage detected: '{forbidden}' in serialized audit")
                return 1
        print("  OK: No secret leakage in serialized FairnessAudit")
        return 0
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return 1


def check_pytest_suite(targets: list, label: str, keyword_filter: str = None) -> int:
    """Run a pytest suite and return 0 on success, 1 on failure.

    Verifies all test files exist first. Does not mask non-zero exits.
    """
    _banner(f"Check: Pytest {label}")

    # Verify all test files exist
    missing = [t for t in targets if not _resolve(t).exists()]
    if missing:
        print(f"  FAIL: Missing test files: {missing}")
        return 1

    cmd = [sys.executable, "-m", "pytest"]
    for t in targets:
        cmd.append(str(_resolve(t)))
    cmd.extend(["-q", "--tb=short"])
    if keyword_filter:
        cmd.extend(["-k", keyword_filter])

    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    # Show last 30 lines of combined output (summary section)
    output_lines = (stdout + "\n" + stderr).split("\n")
    tail = output_lines[-30:] if len(output_lines) > 30 else output_lines
    for line in tail:
        print(f"  {line}")

    if result.returncode != 0:
        print(f"  FAIL: pytest returned exit code {result.returncode}")
        if result.returncode == 2:
            print("  Diagnostics: pytest collection or configuration error.")
        elif result.returncode == 5:
            print("  Diagnostics: no tests collected — test files may be empty or paths changed.")
        else:
            failed_count = sum(1 for line in stdout.split("\n") if "FAILED" in line)
            print(f"  Diagnostics: {failed_count} test(s) failed. See output above.")
        return 1

    # Extract pass count
    pass_count = 0
    for line in stdout.split("\n"):
        if "passed" in line:
            m = re.search(r"(\d+)\s+passed", line)
            if m:
                pass_count = int(m.group(1))

    print(f"  OK: {pass_count} test(s) passed")
    return 0


def check_fairness_tests() -> int:
    """Check 3: Run fairness-specific pytest suite (T01+T02)."""
    return check_pytest_suite(
        FAIRNESS_TEST_TARGETS,
        label="fairness audit suite (T01+T02)",
        keyword_filter=FAIRNESS_KEYWORDS,
    )


def check_s01_regression() -> int:
    """Check 4: Run S01 deterministic place contract tests to guard against regression."""
    return check_pytest_suite(
        S01_TEST_TARGETS,
        label="S01 deterministic place regression guard",
    )


def main() -> int:
    results = [
        check_model_imports(),
        check_secret_redaction(),
        check_fairness_tests(),
        check_s01_regression(),
    ]

    _banner("M013/S02 Fairness & Metadata Coverage Summary")
    passed = sum(1 for r in results if r == 0)
    total = len(results)
    print(f"  {passed}/{total} checks passed")

    if all(r == 0 for r in results):
        print()
        print("  S02 promises verified:")
        print("    ✅ FairnessAudit model contract (6 fields, extra='forbid')")
        print("    ✅ FairnessWarningType enum (5 standardized warnings)")
        print("    ✅ Fairness balancing ≥40% top-5 local target")
        print("    ✅ ChatResponse fairness_audit integration")
        print("    ✅ No secret leakage in audit fields or reasoning_log")
        print("    ✅ S01 deterministic /chat place output (no regression)")
        print()
        print("  RESULT=passed")
        return 0

    print()
    print("  RESULT=failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
