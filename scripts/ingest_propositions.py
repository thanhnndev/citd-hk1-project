#!/usr/bin/env python3
"""Ingestion script: runs PropositionChunker and writes data/tourism_documents.jsonl."""

import json
import sys
from pathlib import Path
from collections import Counter

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from agents.tools.proposition_chunker import PropositionChunker

DOCS_DIR = PROJECT_ROOT / "data" / "cleaned" / "documents"
ENTITIES_DIR = PROJECT_ROOT / "data" / "entities"
OUTPUT_FILE = PROJECT_ROOT / "data" / "tourism_documents.jsonl"


def compute_stats(chunks: list[dict]) -> dict:
    """Compute aggregate stats for the chunk corpus."""
    if not chunks:
        return {}

    lengths = [len(c["text"]) for c in chunks]
    lang_dist = Counter(c.get("language", "unknown") for c in chunks)
    source_type_dist = Counter(c.get("source_type", "unknown") for c in chunks)
    reliability_dist = Counter(c.get("reliability", "unknown") for c in chunks)

    return {
        "total_propositions": len(chunks),
        "avg_length_chars": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "min_length_chars": min(lengths) if lengths else 0,
        "max_length_chars": max(lengths) if lengths else 0,
        "language_distribution": dict(lang_dist),
        "source_type_distribution": dict(source_type_dist),
        "reliability_distribution": dict(reliability_dist),
    }


def write_stats(stats: dict) -> None:
    print("\n=== Ingestion Stats ===")
    print(f"  Total propositions  : {stats['total_propositions']}")
    print(f"  Avg length (chars)    : {stats['avg_length_chars']}")
    print(f"  Min length (chars)   : {stats['min_length_chars']}")
    print(f"  Max length (chars)   : {stats['max_length_chars']}")
    print("  Language dist        : " + ", ".join(
        f"{k}={v}" for k, v in sorted(stats["language_distribution"].items())
    ))
    print("  Source type dist     : " + ", ".join(
        f"{k}={v}" for k, v in sorted(stats["source_type_distribution"].items())
    ))
    print("  Reliability dist     : " + ", ".join(
        f"{k}={v}" for k, v in sorted(stats["reliability_distribution"].items())
    ))
    print()


def main() -> int:
    print(f"Ingesting documents from: {DOCS_DIR}")
    print(f"Ingesting entities from : {ENTITIES_DIR}")

    chunker = PropositionChunker(docs_dir=DOCS_DIR, entities_dir=ENTITIES_DIR)
    chunks = chunker.chunk_all()
    stats = compute_stats(chunks)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    write_stats(stats)
    print(f"Wrote {OUTPUT_FILE}  ({OUTPUT_FILE.stat().st_size:,} bytes)\n")

    # Verification: print first record
    with OUTPUT_FILE.open(encoding="utf-8") as fh:
        first = json.loads(fh.readline())
    print("--- First record preview ---")
    print(json.dumps({k: v for k, v in first.items() if k != "text"}, ensure_ascii=False, indent=2))
    print(f"  text (first 120 chars): {first['text'][:120]}…")

    return 0


if __name__ == "__main__":
    sys.exit(main())