#!/usr/bin/env python3
"""Fail if active repository files contain stale legacy provider references.

The scanner covers code, tests, current docs, config, and dependency manifests. It
intentionally excludes generated/cache/vendor directories and immutable data
corpora under data/ because those files preserve source text, not active provider
contracts.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]

LEGACY_PROVIDER = "goo" + "gle"
LEGACY_PROVIDER_UPPER = LEGACY_PROVIDER.upper()
FORBIDDEN_PATTERNS: tuple[str, ...] = (
    LEGACY_PROVIDER,
    LEGACY_PROVIDER_UPPER,
    LEGACY_PROVIDER.title() + "PlacesService",
    LEGACY_PROVIDER.title() + "RoutesService",
    LEGACY_PROVIDER + "_maps_uri",
    "maps." + LEGACY_PROVIDER + "apis",
    "places." + LEGACY_PROVIDER + "apis",
    "routes." + LEGACY_PROVIDER + "apis",
    LEGACY_PROVIDER + "-maps",
)

TEXT_SUFFIXES = {
    ".css",
    ".env",
    ".example",
    ".html",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}

EXCLUDED_DIRS = {
    ".agents",
    ".git",
    ".gsd",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
}

# Immutable crawled/processed tourism content may quote source pages verbatim.
EXCLUDED_ROOTS = {Path("data")}

_PATTERN_RE = re.compile("|".join(re.escape(pattern) for pattern in FORBIDDEN_PATTERNS))


@dataclass(frozen=True)
class Violation:
    path: Path
    line_number: int
    line: str
    match: str


def is_excluded(path: Path) -> bool:
    relative = path.relative_to(REPO_ROOT) if path.is_absolute() else path
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return True
    return any(relative == root or root in relative.parents for root in EXCLUDED_ROOTS)


def is_text_file(path: Path) -> bool:
    if path.name in {"Makefile", ".env.example", "requirements.txt", "package.json", "bun.lock"}:
        return True
    return path.suffix in TEXT_SUFFIXES


def iter_scanned_files(root: Path = REPO_ROOT) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_dir() or is_excluded(path):
            continue
        if is_text_file(path):
            yield path


def scan_text(text: str, path: Path) -> list[Violation]:
    violations: list[Violation] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in _PATTERN_RE.finditer(line):
            violations.append(Violation(path=path, line_number=line_number, line=line.strip(), match=match.group(0)))
    return violations


def scan_file(path: Path) -> list[Violation]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    return scan_text(text, path.relative_to(REPO_ROOT))


def main() -> int:
    violations = [violation for path in iter_scanned_files() for violation in scan_file(path)]
    if violations:
        print("RESULT=failed")
        print("S05 zero-reference gate found stale provider references:")
        for violation in violations:
            print(f"{violation.path}:{violation.line_number}: {violation.match}: {violation.line}")
        return 1

    print("RESULT=passed")
    print("S05 zero-reference gate passed: no stale provider references in active files.")
    print("Excluded immutable corpus roots: data/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
