#!/usr/bin/env python3
"""Verify the M012 Goong scope reconciliation artifact stays explicit.

The check intentionally reads only docs/ artifacts so it can guard wording drift in
human-readable evidence without coupling to generated or local GSD state.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
RECONCILIATION_DOC = DOCS_ROOT / "M012-GOONG-SCOPE-RECONCILIATION.md"
EVIDENCE_DOC = DOCS_ROOT / "M012-GOONG-VERIFICATION-EVIDENCE.md"

REQUIRED_HEADINGS = (
    "## Credential Boundary",
    "## Producer, Contract, Consumer Map",
    "## In-Scope Requirement Reconciliation",
    "## Requirement Scope Matrix",
    "## Out-of-Scope Active Requirement Gaps",
    "## Verification Surfaces Executors Can Rerun",
)

REQUIRED_TERMS = (
    "GOONG_API_KEY",
    "NEXT_PUBLIC_GOONG_MAPTILES_KEY",
    "RESULT=credential_blocked",
    "credential_blocked",
    "RESULT=passed",
)

IN_SCOPE_REQUIREMENTS = ("R008", "R017", "R019", "R020", "R021", "R032", "R034")
OUT_OF_SCOPE_REQUIREMENTS = ("R007", "R010", "R011", "R026", "R028")

REQUIRED_EVIDENCE_LINKS = (
    "M012-GOONG-SCOPE-RECONCILIATION.md",
    "S07 scope boundary",
)

FORBIDDEN_OVERCLAIMS = (
    re.compile(r"credentialed\s+live\s+(?:goong\s+)?success\s+(?:is\s+)?(?:complete|completed|validated|passed|proven)", re.I),
    re.compile(r"live\s+(?:goong\s+)?(?:places|routes|provider)\s+success\s+(?:is\s+)?(?:complete|completed|validated|passed|proven)", re.I),
    re.compile(r"live\s+browser\s+tile\s+rendering\s+(?:is\s+)?(?:complete|completed|validated|passed|proven)", re.I),
)


@dataclass(frozen=True)
class Failure:
    path: Path
    message: str


def read_doc(path: Path) -> str:
    if not path.is_relative_to(DOCS_ROOT):
        raise ValueError(f"refusing to read non-docs path: {path}")
    return path.read_text(encoding="utf-8")


def require_contains(text: str, path: Path, needles: tuple[str, ...], label: str) -> list[Failure]:
    return [Failure(path, f"missing {label}: {needle}") for needle in needles if needle not in text]


def require_requirement_rows(text: str, path: Path) -> list[Failure]:
    failures: list[Failure] = []
    for requirement in IN_SCOPE_REQUIREMENTS:
        pattern = re.compile(rf"^\|\s*{re.escape(requirement)}\s*\|", re.M)
        if not pattern.search(text):
            failures.append(Failure(path, f"missing in-scope requirement matrix row: {requirement}"))
    for requirement in OUT_OF_SCOPE_REQUIREMENTS:
        pattern = re.compile(rf"^\|\s*{re.escape(requirement)}\s*\|", re.M)
        if not pattern.search(text):
            failures.append(Failure(path, f"missing out-of-scope active gap row: {requirement}"))
    return failures


def require_future_proof_passed_wording(text: str, path: Path) -> list[Failure]:
    patterns = (
        re.compile(r"until\s+[^.\n]*RESULT=passed", re.I),
        re.compile(r"future\s+[^.\n]*RESULT=passed", re.I),
        re.compile(r"RESULT=passed\s+[^.\n]*(?:with\s+real\s+credentials|usable\s+public\s+map\s+tiles\s+key)", re.I),
    )
    if any(pattern.search(text) for pattern in patterns):
        return []
    return [Failure(path, "missing future-proof RESULT=passed wording for credentialed live success")]


def forbid_overclaims(text: str, path: Path) -> list[Failure]:
    failures: list[Failure] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern in FORBIDDEN_OVERCLAIMS:
            if pattern.search(line):
                failures.append(Failure(path, f"forbidden overclaim on line {line_number}: {line.strip()}"))
    return failures


def main() -> int:
    failures: list[Failure] = []
    try:
        reconciliation_text = read_doc(RECONCILIATION_DOC)
        evidence_text = read_doc(EVIDENCE_DOC)
    except OSError as exc:
        print("RESULT=failed")
        print(f"M012 scope reconciliation verifier could not read docs artifact: {exc}")
        return 1

    failures.extend(require_contains(reconciliation_text, RECONCILIATION_DOC, REQUIRED_HEADINGS, "boundary heading"))
    failures.extend(require_contains(reconciliation_text, RECONCILIATION_DOC, REQUIRED_TERMS, "credential/status term"))
    failures.extend(require_requirement_rows(reconciliation_text, RECONCILIATION_DOC))
    failures.extend(require_future_proof_passed_wording(reconciliation_text, RECONCILIATION_DOC))
    failures.extend(forbid_overclaims(reconciliation_text, RECONCILIATION_DOC))
    failures.extend(require_contains(evidence_text, EVIDENCE_DOC, REQUIRED_EVIDENCE_LINKS, "S07 evidence link"))
    failures.extend(forbid_overclaims(evidence_text, EVIDENCE_DOC))

    if failures:
        print("RESULT=failed")
        print("M012 scope reconciliation verifier found boundary drift:")
        for failure in failures:
            print(f"{failure.path.relative_to(REPO_ROOT)}: {failure.message}")
        return 1

    print("RESULT=passed")
    print("M012 scope reconciliation verifier passed: scope headings, credential seams, requirement ids, and evidence links are present.")
    print("Scanned docs only: docs/M012-GOONG-SCOPE-RECONCILIATION.md, docs/M012-GOONG-VERIFICATION-EVIDENCE.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
