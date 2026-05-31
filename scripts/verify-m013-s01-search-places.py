#!/usr/bin/env python3
"""Verify M013/S01 deterministic place contract.

Runs the focused pytest targets for S01 and reports a single RESULT=passed/failed
closeout signal. Never requires GOOGLE_PLACES_API_KEY or network access.

S01 promises verified:
  1. SearchPlacesToolResult contract (provider_status/warnings/reasoning_log/audit,
     extra='forbid', GOOGLE_PLACES source, Google field-mask constant).
  2. Deterministic /chat place output (no citations, no RAG fallback, no LLM override,
     honest failure modes for empty/credential-blocked/upstream_error).
  3. Provider status/source/warnings/reasoning_log exposed while redacting secrets.

Exits 0 with RESULT=passed when all tests pass.
Exits 1 with RESULT=failed and sanitized diagnostics on failure.
"""

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_TARGETS = [
    "backend/tests/test_places_models.py",
    "backend/tests/test_places_service.py",
    "backend/tests/test_agent_place_recommendations.py",
    "backend/tests/test_chat_api.py",
    "backend/tests/test_chat_endpoint.py",
]


def _resolve(target: str) -> Path:
    return PROJECT_ROOT / target


def main() -> int:
    # 1. Verify all test files exist
    missing = [t for t in TEST_TARGETS if not _resolve(t).exists()]
    if missing:
        print("RESULT=failed")
        print(f"Missing test files: {missing}")
        return 1

    # 2. Run pytest
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

    # 3. Parse output
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    # Print combined output (capped for readability)
    output_lines = (stdout + "\n" + stderr).split("\n")
    # Show last 30 lines (summary section)
    tail = output_lines[-30:] if len(output_lines) > 30 else output_lines
    for line in tail:
        print(line)

    if result.returncode != 0:
        print()
        print("RESULT=failed")
        # Sanitize: don't leak any provider payloads or secrets
        if result.returncode == 2:
            print("Diagnostics: pytest collection or configuration error.")
        elif result.returncode == 5:
            print("Diagnostics: no tests collected — test files may be empty or paths changed.")
        else:
            failed_count = 0
            for line in stdout.split("\n"):
                if "FAILED" in line:
                    failed_count += 1
            print(f"Diagnostics: {failed_count} test(s) failed. See output above.")
        return 1

    # 4. Extract pass count from pytest summary
    pass_count = 0
    for line in stdout.split("\n"):
        if "passed" in line:
            # Parse "85 passed" or "85 passed, 77 warnings"
            m = re.search(r"(\d+)\s+passed", line)
            if m:
                pass_count = int(m.group(1))

    print()
    print("=" * 60)
    print("M013/S01 Deterministic Place Contract Verification")
    print("=" * 60)
    print(f"  Test files:  {len(TEST_TARGETS)}")
    print(f"  Tests pass:  {pass_count}")
    print(f"  Failures:    0")
    print("=" * 60)
    print()
    print("RESULT=passed")
    print("S01 promises verified:")
    print("  ✅ SearchPlacesToolResult contract (provider_status/warnings/reasoning_log/audit)")
    print("  ✅ Deterministic /chat place output (no citations, no RAG, no LLM override)")
    print("  ✅ Honest failure modes (empty/credential-blocked/upstream_error)")
    print("  ✅ Provider diagnostics exposed, secrets redacted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
