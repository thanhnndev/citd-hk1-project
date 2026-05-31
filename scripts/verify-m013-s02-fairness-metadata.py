#!/usr/bin/env python3
"""Verification script for M013/S02 fairness and metadata coverage contract.

Checks:
1. FairnessAudit model exists with all required fields.
2. FairnessWarningType enum has all required warning values.
3. ChatResponse carries the fairness_audit field.
4. Pytest test suite for fairness audit passes.
5. No secret leakage in serialized audit fields.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def _banner(msg: str) -> None:
    print(f"\n{'='*60}\n  {msg}\n{'='*60}")


def check_model_imports() -> int:
    """Verify FairnessAudit and FairnessWarningType import cleanly."""
    _banner("Check 1: Model imports")
    try:
        sys.path.insert(0, str(BACKEND))
        from app.models.places import FairnessAudit, FairnessWarningType
        from app.models.response import ChatResponse

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

        expected_warnings = {
            "insufficient_local_candidates",
            "missing_local_factor_metadata",
            "provider_non_ok",
            "route_enrichment_fallback",
            "ensemble_fallback",
        }
        actual_warnings = {w.value for w in FairnessWarningType}
        if actual_warnings != expected_warnings:
            print(f"  FAIL: Warning vocabulary mismatch. Expected {expected_warnings}, got {actual_warnings}")
            return 1
        print(f"  OK: All warning values present: {sorted(expected_warnings)}")

        assert "fairness_audit" in ChatResponse.model_fields, "ChatResponse must have fairness_audit field"
        print("  OK: ChatResponse has fairness_audit field")
        return 0
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return 1


def check_secret_redaction() -> int:
    """Verify serialized audit fields contain no secrets."""
    _banner("Check 2: Secret redaction")
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


def check_pytest() -> int:
    """Run the fairness audit pytest suite."""
    _banner("Check 3: Pytest fairness audit suite")
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         "backend/tests/test_places_models.py",
         "backend/tests/test_agent_place_recommendations.py",
         "-q", "-k", "fairness or Fairness"],
        cwd=ROOT,
        capture_output=True, text=True, timeout=60,
    )
    print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    if result.returncode != 0:
        print("  FAIL: pytest returned non-zero exit code")
        return 1
    if "passed" in result.stdout:
        print("  OK: All fairness-related tests passed")
    return 0


def main() -> int:
    results = [
        check_model_imports(),
        check_secret_redaction(),
        check_pytest(),
    ]
    _banner("Summary")
    passed = sum(1 for r in results if r == 0)
    total = len(results)
    print(f"  {passed}/{total} checks passed")
    if all(r == 0 for r in results):
        print("  RESULT=pass")
        return 0
    print("  RESULT=fail")
    return 1


if __name__ == "__main__":
    sys.exit(main())
