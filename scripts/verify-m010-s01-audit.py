#!/usr/bin/env python3
"""Verify M010/S01 requirements audit report is complete and internally consistent.

Reads docs/M010-S01-AUDIT.md and checks:
  - All expected requirement IDs (R001–R028) are referenced
  - Verdict counts match expected: 20 pass, 2 credential_blocked, 5 fail, 1 out_of_scope
  - No phantom requirement IDs outside the expected range

Exits 0 on success, 1 with diagnostics on failure.
"""

import re
import sys
from pathlib import Path


AUDIT_FILE = Path(__file__).resolve().parent.parent / "docs" / "M010-S01-AUDIT.md"

# Expected verdict assignments per the audit report
EXPECTED_VERDICTS = {
    "pass": [
        "R001", "R002", "R003", "R004", "R005",
        "R006", "R009", "R013", "R014", "R015",
        "R016", "R017", "R018", "R019", "R020",
        "R021", "R022", "R023", "R024", "R025",
    ],
    "credential_blocked": ["R007", "R008"],
    "fail": ["R010", "R011", "R026", "R027", "R028"],
    "out_of_scope": ["R012"],
}

# All unique requirement IDs that should appear (R001–R028, no gaps)
ALL_EXPECTED_IDS = {f"R{n:03d}" for n in range(1, 29)}


def extract_all_ids(text: str) -> set[str]:
    """Extract all R### pattern IDs from the audit text."""
    return set(re.findall(r"\b(R\d{3})\b", text))


def extract_per_requirement_verdicts(text: str) -> dict[str, str]:
    """Extract the verdict from each per-requirement section (### R### — ...).

    Uses the **- Status:** line within the first few lines of each section
    to avoid bleeding into trailing document tables.
    """
    verdicts = {}
    sections = re.split(r"^### (R\d{3})\b", text, flags=re.MULTILINE)
    for i in range(1, len(sections), 2):
        req_id = sections[i]
        body = sections[i + 1] if i + 1 < len(sections) else ""
        # Take only the first 8 lines of the section body (the metadata block)
        # to avoid bleeding into later document tables.
        first_lines = "\n".join(body.split("\n")[:8])
        if "CREDENTIAL_BLOCKED" in first_lines:
            verdicts[req_id] = "credential_blocked"
        elif "OUT_OF_SCOPE" in first_lines:
            verdicts[req_id] = "out_of_scope"
        elif "FAIL" in first_lines:
            verdicts[req_id] = "fail"
        elif "PASS" in first_lines:
            verdicts[req_id] = "pass"
        else:
            verdicts[req_id] = "unknown"
    return verdicts


def main() -> int:
    errors: list[str] = []

    # 1. Check audit file exists
    if not AUDIT_FILE.exists():
        print(f"FAIL: Audit file not found: {AUDIT_FILE}")
        return 1

    text = AUDIT_FILE.read_text(encoding="utf-8")

    # 2. Extract all R### IDs referenced anywhere in the document
    all_found_ids = extract_all_ids(text)

    # 3. Check all expected IDs are present
    missing_ids = ALL_EXPECTED_IDS - all_found_ids
    phantom_ids = all_found_ids - ALL_EXPECTED_IDS

    if missing_ids:
        errors.append(f"Missing requirement IDs: {sorted(missing_ids)}")
    if phantom_ids:
        errors.append(f"Phantom requirement IDs (outside R001–R028): {sorted(phantom_ids)}")

    # 4. Extract per-requirement verdicts from section headers
    verdict_map = extract_per_requirement_verdicts(text)

    # 5. Count verdicts
    counts = {"pass": 0, "credential_blocked": 0, "fail": 0, "out_of_scope": 0, "unknown": 0}
    for req_id, verdict in verdict_map.items():
        counts[verdict] = counts.get(verdict, 0) + 1

    # 6. Check verdict counts match expected
    expected_counts = {
        "pass": len(EXPECTED_VERDICTS["pass"]),
        "credential_blocked": len(EXPECTED_VERDICTS["credential_blocked"]),
        "fail": len(EXPECTED_VERDICTS["fail"]),
        "out_of_scope": len(EXPECTED_VERDICTS["out_of_scope"]),
    }

    for verdict in ["pass", "credential_blocked", "fail", "out_of_scope"]:
        if counts[verdict] != expected_counts[verdict]:
            errors.append(
                f"Verdict count mismatch for '{verdict}': "
                f"expected {expected_counts[verdict]}, found {counts[verdict]}"
            )

    # 7. Verify expected IDs map to correct verdicts
    for verdict, expected_ids in EXPECTED_VERDICTS.items():
        for req_id in expected_ids:
            actual = verdict_map.get(req_id)
            if actual != verdict:
                errors.append(
                    f"Verdict mismatch for {req_id}: expected '{verdict}', got '{actual}'"
                )

    # 8. Check total unique IDs
    total_unique = len(ALL_EXPECTED_IDS)
    total_found = len(all_found_ids & ALL_EXPECTED_IDS)
    if total_found != total_unique:
        errors.append(
            f"Total unique IDs: expected {total_unique}, found {total_found}"
        )

    # 9. Print summary
    active_count = counts["pass"] + counts["credential_blocked"] + counts["fail"]
    print("=" * 60)
    print("M010/S01 Audit Verification Report")
    print("=" * 60)
    print(f"  Audit file:          {AUDIT_FILE}")
    print(f"  Unique IDs found:    {total_found}/{total_unique}")
    print(f"  PASS:                {counts['pass']}")
    print(f"  CREDENTIAL_BLOCKED:  {counts['credential_blocked']}")
    print(f"  FAIL:                {counts['fail']}")
    print(f"  OUT_OF_SCOPE:        {counts['out_of_scope']}")
    print(f"  Unknown:             {counts['unknown']}")
    print(f"  Active (non-OOS):    {active_count}")
    print("=" * 60)

    if errors:
        print("\nERRORS:")
        for err in errors:
            print(f"  ❌ {err}")
        print(f"\nVerification FAILED with {len(errors)} error(s).")
        return 1
    else:
        print("\n✅ All checks passed. Audit report is complete and consistent.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
