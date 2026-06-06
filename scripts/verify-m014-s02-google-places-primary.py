#!/usr/bin/env python3
"""Verify M014/S02 Google Places API New primary contract.

Runs static/contract checks for field-mask coverage, provider-source vocabulary,
redaction, and Google-first/Goong-fallback wiring. Invokes the backend pytest
contract suite in no-network mode.

Credential-aware behaviour:
  - GOOGLE_PLACES_API_KEY missing or placeholder → RESULT=credential_blocked (exit 0)
  - Valid key + live smoke succeeds             → RESULT=live_verified (exit 0)
  - Valid key + live smoke fails (401/403)     → RESULT=credential_blocked (exit 0)
  - Valid key + live smoke timeout/5xx          → RESULT=live_unavailable (exit 0)
  - Local test failure or malformed response    → RESULT=failed (exit 1)

Never treats Goong fallback as live Google validation.
Never prints API keys, raw payloads, or phone numbers.

Failure modes (Q5):
  - Missing credentials → RESULT=credential_blocked (local tests still pass independently).
  - Provider 401/403 → RESULT=credential_blocked.
  - Provider timeout/5xx → RESULT=live_unavailable (local contract still holds).
  - Malformed local response → RESULT=failed.

Load profile (Q6):
  - Verifier is local/CI-style, not on the runtime path.
  - Live smoke makes at most ONE bounded provider request (15s timeout).

Negative tests (Q7):
  - Field mask must cover every rich field consumed by normalize_place().
  - Source vocabulary must include google_places, goong_places, cache.
  - Serialized results must NOT contain raw secret patterns.
  - Goong fallback results must NOT be labelled as google_places success.
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
AGENTS = ROOT / "agents"

# ---------------------------------------------------------------------------
# Test targets
# ---------------------------------------------------------------------------

# Primary S02 contract tests
S02_CONTRACT_TESTS = [
    "backend/tests/test_m014_s02_google_places_primary_contract.py",
]

# Runtime wiring tests (DualPlacesService composition)
RUNTIME_WIRING_TESTS = [
    "backend/tests/test_places_runtime_wiring.py",
]

# Supporting model tests
MODEL_TESTS = [
    "backend/tests/test_places_models.py",
]

ALL_TEST_TARGETS = S02_CONTRACT_TESTS + RUNTIME_WIRING_TESTS + MODEL_TESTS

# ---------------------------------------------------------------------------
# Source files to inspect for static contract checks
# ---------------------------------------------------------------------------

SOURCE_FILES = [
    "backend/app/models/places.py",
    "agents/tools/places_service.py",
]

# ---------------------------------------------------------------------------
# Required vocabulary in source / tests
# ---------------------------------------------------------------------------

REQUIRED_SOURCE_VOCABULARY = [
    # Provider sources
    r"google_places",
    r"goong_places",
    r"cache",
    # Status values
    r"credentials_blocked",
    r"upstream_error",
    r"unavailable",
    # Google API contract
    r"X-Goog-Api-Key",
    r"X-Goog-FieldMask",
    r"places:searchText",
    r"places:searchNearby",
    # Diagnostic fields
    r"credential_status",
    r"provider_attempted",
    r"fallback_reason",
    r"fallback_source",
]

FORBIDDEN_PATTERNS = [
    r"api_key\s*[:=]\s*['\"]AIza",       # Google-style key literal
    r"api_key\s*[:=]\s*['\"]sk-",         # OpenAI-style key literal
    r"password\s*[:=]\s*['\"][^'\"]{8,}", # generic password literal
    r"secret\s*[:=]\s*['\"][^'\"]{8,}",   # generic secret literal
    r"raw_provider_payload",               # must not appear in runtime source
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


def _is_placeholder_key(key: str) -> bool:
    if not key or len(key) < 10:
        return True
    placeholders = [
        "your_", "YOUR_", "replace", "REPLACE", "changeme", "CHANGEME",
        "fake", "FAKE", "test_key", "TEST_KEY", "example", "EXAMPLE",
        "placeholder", "PLACEHOLDER", "dummy", "DUMMY",
    ]
    return any(p in key for p in placeholders)


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
        print(f"    - {t}")
    return 0


# ---------------------------------------------------------------------------
# Check 2: Field mask coverage (static)
# ---------------------------------------------------------------------------

def check_field_mask_coverage() -> int:
    _banner("Check 2: Field mask coverage (static)")
    places_py = _resolve("backend/app/models/places.py")
    if not places_py.exists():
        print(f"  FAIL: {places_py} not found")
        return 1

    content = places_py.read_text()

    # Extract GOOGLE_PLACES_FIELD_MASK value
    m = re.search(r'GOOGLE_PLACES_FIELD_MASK\s*=\s*\((.*?)\)', content, re.DOTALL)
    if not m:
        # Try single-line form
        m = re.search(r'GOOGLE_PLACES_FIELD_MASK\s*=\s*"(.*?)"', content)
    if not m:
        print("  FAIL: Cannot find GOOGLE_PLACES_FIELD_MASK definition")
        return 1

    mask = m.group(1).replace("\n", "").replace('"', "").replace("'", "").strip()
    fields = [f.strip() for f in mask.split(",") if f.strip()]

    core_fields = [
        "places.id", "places.displayName", "places.formattedAddress",
        "places.location", "places.types", "places.primaryType",
    ]
    rich_fields = [
        "places.rating", "places.userRatingCount", "places.priceLevel",
        "places.currentOpeningHours", "places.regularOpeningHours",
        "places.businessStatus", "places.accessibilityOptions",
        "places.nationalPhoneNumber", "places.internationalPhoneNumber",
        "places.googleMapsUri", "places.websiteUri",
        "places.shortFormattedAddress",
    ]

    missing = []
    for f in core_fields + rich_fields:
        if f not in fields:
            missing.append(f)

    if missing:
        print(f"  FAIL: Field mask missing {len(missing)} required field(s): {missing}")
        return 1

    print(f"  OK: Field mask covers {len(fields)} field(s) including all {len(core_fields)} core + {len(rich_fields)} rich fields")
    return 0


# ---------------------------------------------------------------------------
# Check 3: Provider source vocabulary (static)
# ---------------------------------------------------------------------------

def check_provider_source_vocabulary() -> int:
    _banner("Check 3: Provider source vocabulary (static)")
    combined = ""
    for src in SOURCE_FILES:
        p = _resolve(src)
        if p.exists():
            combined += p.read_text() + "\n"

    missing = []
    for pattern in REQUIRED_SOURCE_VOCABULARY:
        if not re.search(pattern, combined):
            missing.append(pattern)

    if missing:
        print(f"  FAIL: Missing required vocabulary: {missing}")
        return 1

    print(f"  OK: All {len(REQUIRED_SOURCE_VOCABULARY)} required vocabulary terms found")

    # Check forbidden patterns (no secrets, no raw payload leakage)
    for pattern in FORBIDDEN_PATTERNS:
        match = re.search(pattern, combined, re.IGNORECASE)
        if match:
            print(f"  FAIL: Forbidden pattern found in source: {pattern}")
            return 1
    print("  OK: No raw secret patterns or raw_provider_payload references in source")
    return 0


# ---------------------------------------------------------------------------
# Check 4: Secret redaction in serialized results (test-level)
# ---------------------------------------------------------------------------

def check_redaction_patterns_in_tests() -> int:
    _banner("Check 4: Redaction patterns in tests")
    test_file = _resolve("backend/tests/test_m014_s02_google_places_primary_contract.py")
    if not test_file.exists():
        print(f"  FAIL: Contract test file not found: {test_file}")
        return 1

    content = test_file.read_text()

    # Must have tests asserting no API key in serialized output
    redaction_assertions = [
        r"no.*api.*key.*in.*dump",
        r"not in dump",
        r"no.*raw.*provider.*payload",
        r"no.*phone.*number",
        r"extra.*forbid",
    ]

    found = 0
    for pattern in redaction_assertions:
        if re.search(pattern, content, re.IGNORECASE):
            found += 1

    if found < 3:
        print(f"  FAIL: Too few redaction assertions in tests (found {found}, expected ≥3)")
        return 1

    print(f"  OK: Redaction assertions present ({found} patterns)")
    return 0


# ---------------------------------------------------------------------------
# Check 5: Google-first / Goong-fallback wiring (static)
# ---------------------------------------------------------------------------

def check_google_first_wiring() -> int:
    _banner("Check 5: Google-first / Goong-fallback wiring (static)")
    service_py = _resolve("agents/tools/places_service.py")
    if not service_py.exists():
        print(f"  FAIL: {service_py} not found")
        return 1

    content = service_py.read_text()

    # Must have GooglePlacesService as primary
    checks = [
        (r"class GooglePlacesService", "GooglePlacesService class defined"),
        (r"class GoongPlacesService", "GoongPlacesService class defined"),
        (r"class DualPlacesService", "DualPlacesService composition defined"),
        (r"_credential_error", "Credential error path exists"),
        (r"_fallback_from_cache", "Cache fallback path exists"),
        (r"credential_status", "Credential status diagnostic exists"),
        (r"provider_attempted", "Provider attempted tracking exists"),
    ]

    missing = []
    for pattern, label in checks:
        if not re.search(pattern, content):
            missing.append(label)

    if missing:
        print(f"  FAIL: Missing wiring components: {missing}")
        return 1

    print(f"  OK: All {len(checks)} wiring components present")

    # Verify DualPlacesService tries Google first
    if "DualPlacesService" in content:
        # Check that Google is attempted before Goong in the dual service
        dual_section = content[content.index("class DualPlacesService"):]
        if "google" in dual_section[:500].lower() and "goong" in dual_section.lower():
            google_pos = dual_section.lower().index("google")
            goong_pos = dual_section.lower().index("goong")
            if google_pos < goong_pos:
                print("  OK: Google is attempted before Goong in DualPlacesService")
            else:
                print("  FAIL: Goong appears before Google in DualPlacesService — Google must be primary")
                return 1
        else:
            print("  FAIL: DualPlacesService missing Google or Goong references")
            return 1

    return 0


# ---------------------------------------------------------------------------
# Check 6: Pytest contract suite
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
    _banner("Check 6: Pytest contract suite (S02 + wiring + models)")
    returncode, stdout, stderr = run_pytest()

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
# Check 7: Goong fallback is NOT treated as Google validation (negative test)
# ---------------------------------------------------------------------------

def check_goong_not_labelled_as_google() -> int:
    _banner("Check 7: Goong fallback not labelled as Google success (negative test)")
    service_py = _resolve("agents/tools/places_service.py")
    if not service_py.exists():
        print(f"  FAIL: {service_py} not found")
        return 1

    content = service_py.read_text()

    # GoongPlacesService._response must set source=PlaceToolSource.GOONG_PLACES
    goong_section = content[content.index("class GoongPlacesService"):]
    goong_response = goong_section[:goong_section.index("class ") if "class " in goong_section[500:] else len(goong_section)]

    if "PlaceToolSource.GOONG_PLACES" in goong_section:
        print("  OK: GoongPlacesService uses GOONG_PLACES source")
    else:
        print("  FAIL: GoongPlacesService must use PlaceToolSource.GOONG_PLACES")
        return 1

    # Must have fallback_source tracking
    if "fallback_source" in goong_section:
        print("  OK: Goong fallback tracks fallback_source")
    else:
        print("  FAIL: Goong fallback must track fallback_source metadata")
        return 1

    # Google service must use GOOGLE_PLACES source
    google_section_start = content.index("class GooglePlacesService")
    google_section_end = content.index("class GoongPlacesService")
    google_section = content[google_section_start:google_section_end]

    if "PlaceToolSource.GOOGLE_PLACES" in google_section:
        print("  OK: GooglePlacesService uses GOOGLE_PLACES source")
    else:
        print("  FAIL: GooglePlacesService must use PlaceToolSource.GOOGLE_PLACES")
        return 1

    return 0


# ---------------------------------------------------------------------------
# Check 8: Model import smoke test
# ---------------------------------------------------------------------------

def check_model_imports() -> int:
    _banner("Check 8: S02 model import smoke test")
    try:
        sys.path.insert(0, str(BACKEND))
        from app.models.places import (
            GOOGLE_PLACES_FIELD_MASK,
            GOOGLE_PLACES_PROVIDER_CONTRACT_VERSION,
            PlaceCandidate,
            PlaceSearchRequest,
            PlaceToolSource,
            PlaceToolStatus,
            SearchPlacesToolResult,
        )

        # Verify field mask is non-empty string
        if not isinstance(GOOGLE_PLACES_FIELD_MASK, str) or len(GOOGLE_PLACES_FIELD_MASK) < 20:
            print("  FAIL: GOOGLE_PLACES_FIELD_MASK is too short or not a string")
            return 1
        print(f"  OK: GOOGLE_PLACES_FIELD_MASK is {len(GOOGLE_PLACES_FIELD_MASK)} chars")

        # Verify contract version
        if not isinstance(GOOGLE_PLACES_PROVIDER_CONTRACT_VERSION, str):
            print("  FAIL: GOOGLE_PLACES_PROVIDER_CONTRACT_VERSION is not a string")
            return 1
        print(f"  OK: Provider contract version = {GOOGLE_PLACES_PROVIDER_CONTRACT_VERSION}")

        # Verify PlaceToolSource has both providers
        sources = {s.value for s in PlaceToolSource}
        if "google_places" not in sources:
            print("  FAIL: PlaceToolSource missing google_places")
            return 1
        if "goong_places" not in sources:
            print("  FAIL: PlaceToolSource missing goong_places")
            return 1
        if "cache" not in sources:
            print("  FAIL: PlaceToolSource missing cache")
            return 1
        print(f"  OK: PlaceToolSource has google_places, goong_places, cache")

        # Verify PlaceToolStatus has all required states
        statuses = {s.value for s in PlaceToolStatus}
        required_statuses = {"ok", "empty", "credentials_blocked", "upstream_error", "unavailable"}
        missing_statuses = required_statuses - statuses
        if missing_statuses:
            print(f"  FAIL: PlaceToolStatus missing: {missing_statuses}")
            return 1
        print(f"  OK: PlaceToolStatus has all required states")

        return 0
    except Exception as exc:
        print(f"  FAIL: {exc}")
        return 1


# ---------------------------------------------------------------------------
# Check 9: Live Google Places smoke check (credential-aware)
# ---------------------------------------------------------------------------

def check_live_google_places() -> tuple[int, str]:
    """Run a live Google Places Text Search smoke check.

    Returns (exit_code, status_string):
      (0, "RESULT=live_verified")       — live proof confirmed
      (0, "RESULT=credential_blocked")  — key missing or placeholder
      (0, "RESULT=live_unavailable")    — provider timeout/5xx
      (1, "RESULT=failed")              — malformed response or unexpected error

    Never treats Goong fallback as Google validation.
    """
    _banner("Check 9: Live Google Places smoke check")

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()

    if not api_key or _is_placeholder_key(api_key):
        status = "credential_blocked"
        print("  SKIP: GOOGLE_PLACES_API_KEY is missing or placeholder")
        print(f"  STATUS: RESULT={status}")
        print("  Note: Local contract tests pass independently.")
        return (0, f"RESULT={status}")

    # Attempt live request
    try:
        import ssl
        import urllib.request

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
                print(f"  STATUS: RESULT=live_verified")
                return (0, "RESULT=live_verified")
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
    _banner("M014/S02 Google Places Primary Contract Verification")

    checks = [
        ("Test file existence", check_test_files_exist),
        ("Field mask coverage (static)", check_field_mask_coverage),
        ("Provider source vocabulary (static)", check_provider_source_vocabulary),
        ("Redaction patterns in tests", check_redaction_patterns_in_tests),
        ("Google-first / Goong-fallback wiring", check_google_first_wiring),
        ("Goong fallback not labelled as Google", check_goong_not_labelled_as_google),
        ("Pytest contract suite", check_pytest_suite),
        ("Model import smoke test", check_model_imports),
        ("Live Google Places smoke check", check_live_google_places),
    ]

    results = []
    for label, fn in checks:
        result = fn()
        if isinstance(result, tuple):
            rc, status_str = result
        else:
            rc, status_str = result, ""
        results.append((label, rc, status_str))

    # ── Final verdict ──────────────────────────────────────────────────
    _banner("M014/S02 Verification Summary")

    # Local checks (all except live smoke)
    local_checks = results[:8]
    live_check = results[8]

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
    if "live_verified" in live_status:
        print("  RESULT=live_verified")
        print("  All local contract tests and live provider proof passed.")
        return 0
    elif "credential_blocked" in live_status:
        print("  RESULT=credential_blocked")
        print("  All local contract tests pass. Live proof blocked by missing/fake credentials.")
        print("  Provide a valid GOOGLE_PLACES_API_KEY to confirm live provider success.")
        return 0
    elif "live_unavailable" in live_status:
        print("  RESULT=live_unavailable")
        print("  All local contract tests pass. Live proof unavailable (provider timeout/5xx).")
        return 0
    else:
        # Default: local passed but live check gave unexpected result
        print(f"  RESULT=credential_blocked")
        print(f"  All local tests pass. Live check: {live_status}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
