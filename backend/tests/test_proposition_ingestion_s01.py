"""
S01 Verification Test Suite — Proposition Ingestion Pipeline

Tests that scripts/ingest_propositions.py:
- Exits 0 and produces 500–800 chunks (actual count printed for observability)
- All JSONL rows have all 9 required fields
- corpus_loader.load_proposition_corpus() loads all chunks without ValueError
- Each chunk has non-empty text (>10 chars)
- Language distribution includes Vietnamese
- Reliability tiers are valid (high/medium/low)
- Stats output matches actual JSONL content

Run: cd backend && python -m pytest tests/test_proposition_ingestion_s01.py -v --tb=short
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Project root: backend/
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "ingest_propositions.py"
CORPUS_PATH = PROJECT_ROOT / "data" / "tourism_documents.jsonl"
CORPUS_LOADER = PROJECT_ROOT / "backend" / "app" / "services" / "corpus_loader.py"

# Required fields per corpus_loader._PROP_REQUIRED_FIELDS
REQUIRED_FIELDS = (
    "chunk_id",
    "source_id",
    "title",
    "domain",
    "source_type",
    "reliability",
    "language",
    "location",
    "text",
)

VALID_RELIABILITY_TIERS = {"high", "medium", "low"}
CHUNK_COUNT_MIN = 500
CHUNK_COUNT_MAX = 800
MIN_TEXT_LENGTH = 11  # > 10 chars


class TestIngestionScriptExitCode:
    """Verify the ingestion script runs successfully."""

    def test_ingest_script_exits_zero(self):
        """scripts/ingest_propositions.py must exit with code 0."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        print(f"\n--- STDOUT ---\n{result.stdout}")
        print(f"\n--- STDERR ---\n{result.stderr}")
        assert result.returncode == 0, (
            f"ingest_propositions.py exited {result.returncode}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


class TestCorpusFileExists:
    """Verify the JSONL output was produced."""

    def test_corpus_file_exists(self):
        """data/tourism_documents.jsonl must exist after ingestion."""
        assert CORPUS_PATH.exists(), f"{CORPUS_PATH} was not produced"


class TestChunkCountRange:
    """Verify chunk count falls within the expected band."""

    def test_chunk_count_within_range(self):
        """Total propositions must be between 500 and 800 (inclusive)."""
        assert CORPUS_PATH.exists()
        rows = _load_jsonl(CORPUS_PATH)
        actual_count = len(rows)
        print(f"\nActual chunk count: {actual_count}")
        assert CHUNK_COUNT_MIN <= actual_count <= CHUNK_COUNT_MAX, (
            f"Expected {CHUNK_COUNT_MIN}–{CHUNK_COUNT_MAX} chunks, got {actual_count}"
        )


class TestRequiredFields:
    """Verify every JSONL row has all 9 required fields."""

    def _missing_fields(self, rows: list[dict]) -> list[tuple[int, list[str]]]:
        """Return [(row_num, [missing_fields])] for rows missing fields."""
        issues = []
        for idx, row in enumerate(rows, start=1):
            missing = [f for f in REQUIRED_FIELDS if f not in row or row[f] is None]
            if missing:
                issues.append((idx, missing))
        return issues

    def test_all_rows_have_required_fields(self):
        """Every JSONL row must contain all 9 required fields (chunk_id through text)."""
        rows = _load_jsonl(CORPUS_PATH)
        issues = self._missing_fields(rows)
        if issues:
            sample = issues[:3]
            detail = "\n".join(f"  row {rn}: missing {', '.join(mf)}" for rn, mf in sample)
            pytest.fail(
                f"{len(issues)} rows missing required fields.\n"
                f"Sample issues:\n{detail}"
            )


class TestNonEmptyText:
    """Verify every chunk has text content > 10 characters."""

    def test_each_chunk_text_non_empty(self):
        """Every chunk text must be non-empty and > 10 characters."""
        rows = _load_jsonl(CORPUS_PATH)
        violations = []
        for idx, row in enumerate(rows, start=1):
            text = row.get("text", "")
            if not text or len(text) <= 10:
                violations.append((idx, repr(text[:50])))
        if violations:
            sample = violations[:5]
            detail = "\n".join(f"  row {rn}: text={tv}" for rn, tv in sample)
            pytest.fail(
                f"{len(violations)} chunks have text <= 10 chars.\n"
                f"Sample violations:\n{detail}"
            )


class TestLanguageDistribution:
    """Verify Vietnamese appears in the corpus."""

    def test_vietnamese_present(self):
        """At least one chunk must have language 'vi'."""
        rows = _load_jsonl(CORPUS_PATH)
        langs = {row.get("language", "unknown") for row in rows}
        assert "vi" in langs, f"No Vietnamese chunks found. Languages: {langs}"


class TestReliabilityTiers:
    """Verify all reliability values are valid."""

    def test_all_reliability_tiers_valid(self):
        """Every chunk reliability must be one of: high, medium, low."""
        rows = _load_jsonl(CORPUS_PATH)
        invalid = []
        for idx, row in enumerate(rows, start=1):
            rel = row.get("reliability", "unknown")
            if rel not in VALID_RELIABILITY_TIERS:
                invalid.append((idx, rel))
        if invalid:
            sample = invalid[:5]
            detail = "\n".join(f"  row {rn}: reliability={rv}" for rn, rv in sample)
            pytest.fail(
                f"{len(invalid)} chunks have invalid reliability tiers.\n"
                f"Sample issues:\n{detail}"
            )


class TestCorpusLoaderIntegration:
    """Verify load_proposition_corpus() loads the produced JSONL without errors."""

    def test_load_proposition_corpus_succeeds(self):
        """corpus_loader.load_proposition_corpus() must load all rows without ValueError."""
        import sys as _sys
        _sys.path.insert(0, str(PROJECT_ROOT / "backend"))
        from agents.tools.corpus_loader import load_proposition_corpus

        chunks = load_proposition_corpus(str(CORPUS_PATH))
        assert len(chunks) >= CHUNK_COUNT_MIN, (
            f"Expected >= {CHUNK_COUNT_MIN} chunks from load_proposition_corpus(), got {len(chunks)}"
        )
        # Confirm all required fields are populated
        empty_ids = [c.chunk_id for c in chunks if not c.chunk_id]
        assert not empty_ids, f"Found {len(empty_ids)} chunks with empty chunk_id"
        empty_texts = [c.chunk_id for c in chunks if not c.text or len(c.text) <= 10]
        assert not empty_texts, f"Found {len(empty_texts)} chunks with empty/short text after load"


class TestStatsOutputMatchesCorpus:
    """Verify the ingestion stats reflect actual JSONL content."""

    def test_stats_language_distribution_matches_corpus(self):
        """Language distribution from JSONL must match ingestion stats output."""
        rows = _load_jsonl(CORPUS_PATH)
        lang_counter: dict[str, int] = {}
        for row in rows:
            lang = row.get("language", "unknown")
            lang_counter[lang] = lang_counter.get(lang, 0) + 1

        # Run ingestion script and capture its stats output
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        stdout = result.stdout

        for lang, count in lang_counter.items():
            expected_line = f"{lang}={count}"
            assert expected_line in stdout, (
                f"Stats output missing expected line '{expected_line}'.\n"
                f"Check ingestion output matches JSONL content."
            )

    def test_stats_total_matches_jsonl_line_count(self):
        """Total propositions in stats must equal number of JSONL lines."""
        rows = _load_jsonl(CORPUS_PATH)
        total = len(rows)

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        stdout = result.stdout

        # Find the "Total propositions" line
        total_lines = [l for l in stdout.splitlines() if "Total propositions" in l]
        assert total_lines, "Could not find 'Total propositions' in ingestion output"
        reported = int(total_lines[0].split(":")[-1].strip())
        assert reported == total, (
            f"Stats reports {reported} propositions but JSONL has {total} rows"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _load_jsonl(path: Path) -> list[dict]:
    """Load all non-empty, non-comment lines from a JSONL file."""
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rows.append(json.loads(line))
    return rows