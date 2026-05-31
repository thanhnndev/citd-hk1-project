#!/usr/bin/env python3
"""Verify M014/S03 Recommendation Explanation Contract.

Runs the S03 pytest contract suite and performs static/schema inspection to
confirm that PlaceResult includes score_breakdown and explanation fields and
PlaceExplanation keeps provider/evidence fields.

This is a credential-free, local-only verifier — no live network calls and no
persistent data writes except normal pytest cache artifacts.

Credential-aware behaviour (Q5):
  - All proof is local/contract-level; credential absence must NOT cause failure.
  - Exit 0 when all local tests pass; exit 1 on test failures or schema regressions.

Failure modes (Q5):
  - pytest failures (missing fields, broken imports, contract regressions) → exit 1.
  - Schema fields disappear from PlaceResult/PlaceExplanation → exit 1.
  - Missing test files → exit 1.
  - Credential absence → NOT treated as failure (S03 is local-only).

Load profile (Q6):
  - Verifier is local test orchestration only.
  - No live network, no persistent data writes beyond pytest cache.

Negative tests (Q7):
  - Provider non-OK response paths (E7).
  - Empty candidates (E8).
  - Missing rich metadata graceful degradation (E9).
  - Malformed/redaction-prone text sanitization (E10).
  - Reranker fallback path (E11).
  - Extra-field injection rejection via extra='forbid' (E15).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Test targets
# ---------------------------------------------------------------------------

# Primary S03 contract tests (T01 + T02: explanation contract + provider status)
S03_CONTRACT_TESTS = [
    "backend/tests/test_m014_s03_recommendation_explanation_contract.py",
]

# Chat/follow-up wiring tests (T03)
CHAT_CONTRACT_TESTS = [
    "backend/tests/test_m014_s03_chat_explanation_contract.py",
]

# Existing recommendation tests (regression coverage)
REGRESSION_TESTS = [
    "backend/tests/test_place_recommendation_service.py",
    "backend/tests/test_place_recommendation_reranking.py",
    "backend/tests/test_places_models.py",
    "backend/tests/test_agent_place_recommendations.py",
]

ALL_TEST_TARGETS = S03_CONTRACT_TESTS + CHAT_CONTRACT_TESTS + REGRESSION_TESTS

# ---------------------------------------------------------------------------
# Source files to inspect for static contract checks
# ---------------------------------------------------------------------------

SOURCE_FILES = [
    "backend/app/models/response.py",
    "agents/services/place_recommendation_service.py",
]

# ---------------------------------------------------------------------------
# Required schema fields
# ---------------------------------------------------------------------------

PLACE_RESULT_REQUIRED_FIELDS = [
    "score_breakdown",
    "explanation",
    "final_score",
    "place_id",
    "display_name",
    "location",
    "types",
]

SCORE_BREAKDOWN_REQUIRED_FIELDS = [
    "tree1_locality",
    "tree2_proximity",
    "tree3_quality",
    "s_bag",
    "delta1_fairness",
    "delta2_access",
    "final_score",
    "rank",
]

PLACE_EXPLANATION_REQUIRED_FIELDS = [
    "rank",
    "primary_reason",
    "matched_preferences",
    "local_context",
    "score_factors",
    "fairness_note",
    "accessibility_note",
    "route_summary",
    "provider_source",
    "provider_status",
    "evidence_fields_used",
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
    for line in stdout.split("\n"):
        if "passed" in line:
            m = re.search(r"(\d+)\s+passed", line)
            if m:
                return int(m.group(1))
    return 0


def _parse_fail_count(stdout: str) -> int:
    count = 0
    for line in stdout.split("\n"):
        m = re.search(r"(\d+)\s+failed", line)
        if m:
            count += int(m.group(1))
    return count


# ---------------------------------------------------------------------------
# Check 1: Test file existence
# ---------------------------------------------------------------------------

def check_test_files_exist() -> int:
    _banner("Check 1: Test file existence")
    missing = [t for t in ALL_TEST_TARGETS if not _resolve(t).exists()]
    if missing:
        print(f"  FAIL: Missing test files: {missing}")
        return 1
    print(f"  OK: All {len(ALL_TEST_TARGETS)} test files present")
    for t in ALL_TEST_TARGETS:
        print(f"    ✓ {t}")
    return 0


# ---------------------------------------------------------------------------
# Check 2: Pytest contract suite (S03 + chat + regression)
# ---------------------------------------------------------------------------

def run_pytest() -> tuple[int, str, str]:
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
    _banner("Check 2: Pytest contract suite (S03 + chat + regression)")
    returncode, stdout, stderr = run_pytest()

    output_lines = (stdout + "\n" + stderr).split("\n")
    tail = output_lines[-30:] if len(output_lines) > 30 else output_lines
    for line in tail:
        print(f"  {line}")

    if returncode != 0:
        fail_count = _parse_fail_count(stdout)
        print(f"  FAIL: pytest returned exit code {returncode} ({fail_count} test(s) failed)")
        return 1

    pass_count = _parse_pass_count(stdout)
    print(f"  OK: {pass_count} test(s) passed")
    return 0


# ---------------------------------------------------------------------------
# Check 3: PlaceResult schema inspection (score_breakdown + explanation)
# ---------------------------------------------------------------------------

def check_place_result_schema() -> int:
    _banner("Check 3: PlaceResult schema inspection")
    response_py = _resolve("backend/app/models/response.py")
    if not response_py.exists():
        print(f"  FAIL: {response_py} not found")
        return 1

    content = response_py.read_text()

    # Verify PlaceResult has score_breakdown field
    missing = []
    for field in PLACE_RESULT_REQUIRED_FIELDS:
        if re.search(rf'\b{field}\b.*Field', content) or re.search(rf'\b{field}\s*:', content):
            continue
        # Also check in the model body between class PlaceResult and next class
        class_match = re.search(r'class PlaceResult\(.*?\):(.*?)(?=\nclass |\Z)', content, re.DOTALL)
        if class_match and field not in class_match.group(1):
            missing.append(field)

    if missing:
        print(f"  FAIL: PlaceResult missing fields: {missing}")
        return 1

    print(f"  OK: PlaceResult has all {len(PLACE_RESULT_REQUIRED_FIELDS)} required fields")
    return 0


# ---------------------------------------------------------------------------
# Check 4: ScoreBreakdown schema inspection
# ---------------------------------------------------------------------------

def check_score_breakdown_schema() -> int:
    _banner("Check 4: ScoreBreakdown schema inspection")
    response_py = _resolve("backend/app/models/response.py")
    if not response_py.exists():
        print(f"  FAIL: {response_py} not found")
        return 1

    content = response_py.read_text()

    # Extract ScoreBreakdown class body
    class_match = re.search(r'class ScoreBreakdown\(.*?\):(.*?)(?=\nclass |\Z)', content, re.DOTALL)
    if not class_match:
        print("  FAIL: Cannot find ScoreBreakdown class definition")
        return 1

    body = class_match.group(1)
    missing = [f for f in SCORE_BREAKDOWN_REQUIRED_FIELDS if f not in body]

    if missing:
        print(f"  FAIL: ScoreBreakdown missing fields: {missing}")
        return 1

    print(f"  OK: ScoreBreakdown has all {len(SCORE_BREAKDOWN_REQUIRED_FIELDS)} required fields")
    return 0


# ---------------------------------------------------------------------------
# Check 5: PlaceExplanation schema inspection (provider + evidence fields)
# ---------------------------------------------------------------------------

def check_place_explanation_schema() -> int:
    _banner("Check 5: PlaceExplanation schema inspection (provider + evidence fields)")
    response_py = _resolve("backend/app/models/response.py")
    if not response_py.exists():
        print(f"  FAIL: {response_py} not found")
        return 1

    content = response_py.read_text()

    # Extract PlaceExplanation class body
    class_match = re.search(r'class PlaceExplanation\(.*?\):(.*?)(?=\nclass |\Z)', content, re.DOTALL)
    if not class_match:
        print("  FAIL: Cannot find PlaceExplanation class definition")
        return 1

    body = class_match.group(1)

    # Check extra='forbid' enforcement
    if "extra" not in body or "forbid" not in body:
        print("  FAIL: PlaceExplanation missing extra='forbid' config")
        return 1
    print("  OK: PlaceExplanation has extra='forbid' (no frontend injection)")

    missing = [f for f in PLACE_EXPLANATION_REQUIRED_FIELDS if f not in body]

    if missing:
        print(f"  FAIL: PlaceExplanation missing fields: {missing}")
        return 1

    print(f"  OK: PlaceExplanation has all {len(PLACE_EXPLANATION_REQUIRED_FIELDS)} required fields")
    return 0


# ---------------------------------------------------------------------------
# Check 6: Provider honesty wiring (S02 inheritance)
# ---------------------------------------------------------------------------

def check_provider_honesty_wiring() -> int:
    _banner("Check 6: Provider honesty wiring (provider_source + provider_status)")
    service_py = _resolve("agents/services/place_recommendation_service.py")
    if not service_py.exists():
        print(f"  FAIL: {service_py} not found")
        return 1

    content = service_py.read_text()

    required_patterns = [
        (r"provider_source", "provider_source threading"),
        (r"provider_status", "provider_status threading"),
        (r"PlaceToolSource", "PlaceToolSource import"),
        (r"PlaceToolStatus", "PlaceToolStatus import"),
        (r"_build_place_explanation", "_build_place_explanation function"),
        (r"_reranked_results", "_reranked_results function"),
        (r"_grounded_results", "_grounded_results function"),
    ]

    missing = []
    for pattern, label in required_patterns:
        if not re.search(pattern, content):
            missing.append(label)

    if missing:
        print(f"  FAIL: Missing wiring components: {missing}")
        return 1

    print(f"  OK: All {len(required_patterns)} provider honesty wiring components present")
    return 0


# ---------------------------------------------------------------------------
# Check 7: Redaction boundary verification
# ---------------------------------------------------------------------------

def check_redaction_boundary() -> int:
    _banner("Check 7: Redaction boundary in service code")
    service_py = _resolve("agents/services/place_recommendation_service.py")
    if not service_py.exists():
        print(f"  FAIL: {service_py} not found")
        return 1

    content = service_py.read_text()

    # Must have _redact_text function
    if "_redact_text" not in content:
        print("  FAIL: _redact_text function not found in service")
        return 1

    # Must redact API key patterns
    if "AIza" in content and "redact" not in content.split("AIza")[1][:100]:
        print("  WARN: API key pattern found near redaction — verify redaction applies")

    # Verify _redact_text is called on explanation text fields
    explanation_calls = re.findall(r'_redact_text\(', content)
    if len(explanation_calls) < 3:
        print(f"  WARN: _redact_text called only {len(explanation_calls)} time(s) — expected ≥3")
    else:
        print(f"  OK: _redact_text called {len(explanation_calls)} times")

    # Must not contain raw provider payload pass-through
    if "raw_payload" in content.lower():
        print("  FAIL: raw_payload reference found in service — must not pass raw payloads")
        return 1

    print("  OK: Redaction boundary looks correct")
    return 0


# ---------------------------------------------------------------------------
# Check 8: Runtime import smoke test
# ---------------------------------------------------------------------------

def check_model_imports() -> int:
    _banner("Check 8: S03 model import smoke test")
    backend = ROOT / "backend"
    try:
        sys.path.insert(0, str(backend))
        from app.models.response import (
            PlaceResult,
            PlaceExplanation,
            ScoreBreakdown,
            ChatResponse,
        )

        # Verify PlaceExplanation rejects extra fields
        try:
            PlaceExplanation(
                rank=1,
                primary_reason="test",
                frontend_fabricated="should_fail",
            )
            print("  FAIL: PlaceExplanation accepted extra field (extra='forbid' not enforced)")
            return 1
        except Exception:
            print("  OK: PlaceExplanation rejects extra fields (extra='forbid')")

        # Verify ScoreBreakdown has all 8 fields
        sb = ScoreBreakdown(
            tree1_locality=0.5,
            tree2_proximity=0.5,
            tree3_quality=0.5,
            s_bag=0.5,
            delta1_fairness=0.0,
            delta2_access=0.0,
            final_score=0.5,
            rank=1,
        )
        fields = set(ScoreBreakdown.model_fields.keys())
        expected = set(SCORE_BREAKDOWN_REQUIRED_FIELDS)
        if expected <= fields:
            print(f"  OK: ScoreBreakdown has all {len(expected)} required fields")
        else:
            missing = expected - fields
            print(f"  FAIL: ScoreBreakdown missing fields at runtime: {missing}")
            return 1

        # Verify PlaceExplanation has provider/evidence fields
        exp = PlaceExplanation(rank=1, primary_reason="test")
        exp_fields = set(PlaceExplanation.model_fields.keys())
        expected_exp = set(PLACE_EXPLANATION_REQUIRED_FIELDS)
        if expected_exp <= exp_fields:
            print(f"  OK: PlaceExplanation has all {len(expected_exp)} required fields")
        else:
            missing = expected_exp - exp_fields
            print(f"  FAIL: PlaceExplanation missing fields at runtime: {missing}")
            return 1

        # Verify PlaceResult has score_breakdown and explanation
        from app.models.request import LatLng
        place = PlaceResult(
            place_id="places/test",
            display_name="Test Place",
            formatted_address="Test",
            location=LatLng(lat=10.0, lng=104.0),
            types=["restaurant"],
            local_factor=0.5,
            final_score=0.5,
            score_breakdown=sb,
            map_uri="https://maps.example/test",
        )
        if place.explanation is not None and place.score_breakdown is not None:
            print("  OK: PlaceResult has score_breakdown and explanation")
        else:
            print("  FAIL: PlaceResult missing score_breakdown or explanation")
            return 1

        return 0

    except Exception as exc:
        print(f"  FAIL: {exc}")
        return 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    _banner("M014/S03 Recommendation Explanation Contract Verification")

    checks = [
        ("Test file existence", check_test_files_exist),
        ("Pytest contract suite", check_pytest_suite),
        ("PlaceResult schema inspection", check_place_result_schema),
        ("ScoreBreakdown schema inspection", check_score_breakdown_schema),
        ("PlaceExplanation schema inspection", check_place_explanation_schema),
        ("Provider honesty wiring", check_provider_honesty_wiring),
        ("Redaction boundary", check_redaction_boundary),
        ("Model import smoke test", check_model_imports),
    ]

    results = []
    for label, fn in checks:
        try:
            rc = fn()
        except Exception as exc:
            print(f"  EXCEPTION in {label}: {exc}")
            rc = 1
        results.append((label, rc))

    # ── Final verdict ──────────────────────────────────────────────────
    _banner("M014/S03 Verification Summary")

    passed = sum(1 for _, rc in results if rc == 0)
    failed = [(label, rc) for label, rc in results if rc != 0]
    total = len(results)

    print(f"  {passed}/{total} checks passed")

    if failed:
        print("\n  Failed checks:")
        for label, rc in failed:
            print(f"    ✗ {label} (exit {rc})")
        print("\n  RESULT=failed")
        return 1
    else:
        print("\n  RESULT=contract_verified")
        print("  All S03 contract tests pass, schema fields intact, provider honesty wired.")
        print("  This verifier is credential-free — all proof is local/contract-level.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
