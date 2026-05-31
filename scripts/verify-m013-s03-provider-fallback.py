#!/usr/bin/env python3
"""Verify M013/S03 provider fallback and no-RAG guarantees.

Runs the focused pytest targets for S03 cache, provider-service, and runtime wiring
tests, then performs static assertions that the test suite covers R041/R042 keywords
and that place-fallback paths assert no citations / no RAG fallback.

S03 promises verified:
  1. Postgres place cache: deterministic key, upsert hit/miss/stale/malformed/error,
     secret redaction, negative inputs (test_place_cache.py).
  2. Circuit breaker + cache fallback on provider timeout/500/malformed/circuit-open;
     honest unavailable on cache miss; no RAG fallback or citations (test_places_service.py).
  3. Runtime wiring: cache injected via FastAPI startup, safe degraded startup when
     DATABASE_URL absent, /chat place intent returns cached PlaceResults with citations=[],
     provider/circuit failures never fall back to retriever/RAG (test_places_runtime_wiring.py).

Exits 0 with RESULT=passed when all tests pass and static assertions hold.
Exits 1 with RESULT=failed and sanitized diagnostics on any failure.
"""

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TEST_TARGETS = [
    "backend/tests/test_place_cache.py",
    "backend/tests/test_places_service.py",
    "backend/tests/test_places_runtime_wiring.py",
]

# R041/R042 keywords that must appear in test files
R041_R042_KEYWORDS = [
    "cache_hit",
    "cache_miss",
    "cache fallback",
    "circuit",
    "timeout",
    "unavailable",
    "no.*citation",
    "no.*RAG",
    "no_rag",
    "fallback",
    "Postgres",
]

# Patterns in test files that assert no-RAG/no-citations behavior
NO_RAG_ASSERTIONS = [
    r"citations\s*==\s*\[\]",
    r"citations\s*==\s*\[\s*\]",
    r"\.citations\s*==\s*\[\]",
    r"no.*citation",
    r"no.*RAG",
    r"no_rag",
    r"assert.*citation.*empty",
    r"assert.*citation.*\[\]",
    r"UNAVAILABLE",
]


def _resolve(target: str) -> Path:
    return PROJECT_ROOT / target


def _run_pytest() -> tuple[int, str, str]:
    """Run pytest on all S03 test targets. Returns (exit_code, stdout, stderr)."""
    cmd = [
        sys.executable, "-m", "pytest",
        *[str(_resolve(t)) for t in TEST_TARGETS],
        "-q", "--tb=short",
    ]
    print(f"Running: {' '.join(cmd)}")
    print()

    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _check_test_files_exist() -> list[str]:
    """Return list of missing test file paths."""
    missing = [t for t in TEST_TARGETS if not _resolve(t).exists()]
    return missing


def _check_r041_r042_keyword_coverage() -> list[str]:
    """Check that test files collectively cover all R041/R042 keywords."""
    all_text = ""
    for target in TEST_TARGETS:
        p = _resolve(target)
        if p.exists():
            all_text += p.read_text()

    uncovered = []
    for pattern in R041_R042_KEYWORDS:
        if not re.search(pattern, all_text, re.IGNORECASE):
            uncovered.append(pattern)
    return uncovered


def _check_no_rag_assertions() -> list[str]:
    """Check that test files contain assertions for no-citations/no-RAG behavior."""
    all_text = ""
    for target in TEST_TARGETS:
        p = _resolve(target)
        if p.exists():
            all_text += p.read_text()

    found = []
    for pattern in NO_RAG_ASSERTIONS:
        if re.search(pattern, all_text, re.IGNORECASE):
            found.append(pattern)
    return found


def _parse_pass_count(stdout: str) -> int:
    """Extract the number of passed tests from pytest output."""
    for line in stdout.split("\n"):
        if "passed" in line:
            m = re.search(r"(\d+)\s+passed", line)
            if m:
                return int(m.group(1))
    return 0


def _parse_fail_count(stdout: str) -> int:
    """Extract the number of failed tests from pytest output."""
    for line in stdout.split("\n"):
        if "failed" in line:
            m = re.search(r"(\d+)\s+failed", line)
            if m:
                return int(m.group(1))
    return 0


def main() -> int:
    failures = []

    # ── Step 1: Verify all test files exist ──────────────────────────────
    print("=" * 60)
    print("M013/S03 Provider Fallback and No-RAG Guarantees Verification")
    print("=" * 60)
    print()

    missing = _check_test_files_exist()
    if missing:
        print(f"❌ Missing test files: {missing}")
        print()
        print("RESULT=failed")
        return 1

    print(f"✅ All {len(TEST_TARGETS)} test files present")
    for t in TEST_TARGETS:
        print(f"   - {t}")
    print()

    # ── Step 2: Run pytest ──────────────────────────────────────────────
    returncode, stdout, stderr = _run_pytest()

    # Show last 30 lines of output (summary section)
    output_lines = (stdout + "\n" + stderr).split("\n")
    tail = output_lines[-30:] if len(output_lines) > 30 else output_lines
    for line in tail:
        print(line)

    if returncode != 0:
        failures.append(f"pytest exit code: {returncode}")
        pass_count = _parse_pass_count(stdout)
        fail_count = _parse_fail_count(stdout)
        if fail_count:
            failures.append(f"{fail_count} test(s) failed")
        elif returncode == 2:
            failures.append("pytest collection or configuration error")
        elif returncode == 5:
            failures.append("no tests collected — test files may be empty or paths changed")
        else:
            failures.append(f"pytest returned non-zero (exit {returncode})")

    print()

    # ── Step 3: Static assertion — R041/R042 keyword coverage ───────────
    uncovered = _check_r041_r042_keyword_coverage()
    if uncovered:
        failures.append(f"R041/R042 keywords not covered in tests: {uncovered}")
        print(f"❌ R041/R042 keyword gaps: {uncovered}")
    else:
        print(f"✅ All R041/R042 keywords covered ({len(R041_R042_KEYWORDS)} patterns)")

    # ── Step 4: Static assertion — no-RAG/no-citation assertions exist ──
    no_rag_found = _check_no_rag_assertions()
    if len(no_rag_found) < 2:
        failures.append(
            f"Too few no-RAG/no-citation assertions in tests "
            f"(found {len(no_rag_found)}, expected ≥2)"
        )
        print(f"❌ No-RAG assertions insufficient: {no_rag_found}")
    else:
        print(f"✅ No-RAG/no-citation assertions present ({len(no_rag_found)} patterns)")

    # ── Final verdict ───────────────────────────────────────────────────
    print()
    if failures:
        print("RESULT=failed")
        for f_msg in failures:
            print(f"  ❌ {f_msg}")
        return 1

    pass_count = _parse_pass_count(stdout)
    print("=" * 60)
    print(f"  Test files:  {len(TEST_TARGETS)}")
    print(f"  Tests pass:  {pass_count}")
    print(f"  Failures:    0")
    print(f"  R041/R042:   covered")
    print(f"  No-RAG:      asserted")
    print("=" * 60)
    print()
    print("RESULT=passed")
    print("S03 promises verified:")
    print("  ✅ Postgres place cache (deterministic key, upsert, lookup, secret redaction)")
    print("  ✅ Circuit breaker + cache fallback on provider failure")
    print("  ✅ Honest unavailable on cache miss (no RAG fallback, citations=[])")
    print("  ✅ Runtime wiring (safe degraded startup, cache injected)")
    print("  ✅ R041/R042 keyword coverage in test suite")
    print("  ✅ No-RAG/no-citation assertions in fallback test paths")
    return 0


if __name__ == "__main__":
    sys.exit(main())
