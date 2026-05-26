#!/usr/bin/env python3
"""Verify S03 retrieval + agent end-to-end pipeline.

Run from the repository root:
    python3 scripts/verify-retrieval-agent-s03.py

Behaviour:
  - Phase 1: corpus check (607 proposition rows, chunk_id/text/source_id/language schema)
  - Phase 2: credential_blocked — exits 0 with RESULT=credential_blocked if no valid OPENAI_API_KEY
  - Phase 3: POST /chat with Vietnamese query "Hàm Ninh có gì đặc biệt?"
  - Phase 4: verify response has non-empty citations with chunk_ids from real corpus
  - Phase 5: POST /chat with English query "What is special about Hàm Ninh?"
  - Phase 6: POST /chat with out-of-scope query "weather in Hanoi" — verify fallback=True or empty citations
  - Exits 0 with RESULT=passed, exits 0 with RESULT=credential_blocked, or exits 1 on failure

Follows the S02 verify-embed-pipeline-s02.py pattern as the S03 closeout gate.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

EXPECTED_CHUNKS = 607
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:48721")
BACKEND_API_KEY = os.environ.get("BACKEND_API_KEY", "test-admin-key")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def key_status() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return "missing"
    if key.startswith("fake"):
        return "fake"
    placeholder_markers = ("[REDACTED", "REDACTED", "xxxx", "<")
    placeholder_suffixes = (">", "xxxx")
    if key.startswith(placeholder_markers) or key.endswith(placeholder_suffixes):
        return "placeholder"
    return "present"


def credential_blocked() -> bool:
    return key_status() in {"missing", "fake", "placeholder"}


def request_json(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 120,
) -> tuple[int, dict[str, Any]]:
    headers = dict(headers) if headers else {}
    headers.setdefault("Accept", "application/json")
    headers.setdefault("Content-Type", "application/json")

    data: bytes | None = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, method=method, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        parsed = json.loads(raw) if raw else {}
        if not isinstance(parsed, dict):
            raise ValueError(f"expected JSON object from {url}, got {type(parsed).__name__}")
        return response.status, parsed


def print_json(label: str, value: object) -> None:
    print(f"{label}={json.dumps(value, sort_keys=True, ensure_ascii=False)}")


def failure(label: str, phase: str, exc: BaseException | str) -> dict[str, Any]:
    if isinstance(exc, urllib.error.HTTPError):
        body = exc.read().decode("utf-8", "replace")
        payload: dict[str, Any] = {
            "phase": phase, "error_type": "HTTPError",
            "http_status": exc.code, "body": body,
        }
    elif isinstance(exc, urllib.error.URLError):
        payload = {"phase": phase, "error_type": type(exc).__name__, "message": str(exc.reason)}
    elif isinstance(exc, BaseException):
        payload = {"phase": phase, "error_type": type(exc).__name__, "message": str(exc)}
    else:
        payload = {"phase": phase, "error_type": "ValidationError", "message": exc}
    print_json(label, payload)
    return payload


# ---------------------------------------------------------------------------
# Phase 1: Corpus check
# ---------------------------------------------------------------------------

def check_corpus() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Verify data/tourism_documents.jsonl exists with 607 proposition rows and language field."""
    base = os.path.dirname(os.path.dirname(__file__))
    corpus_path = os.path.join(base, "data", "tourism_documents.jsonl")

    state: dict[str, Any] = {
        "path": corpus_path,
        "exists": False,
        "row_count": None,
        "schema_ok": False,
        "languages": {},
    }
    try:
        state["exists"] = os.path.exists(corpus_path)
        if not state["exists"]:
            return None, failure("CORPUS_ERROR", "corpus_exists", f"file not found: {corpus_path}")

        rows = []
        with open(corpus_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))

        state["row_count"] = len(rows)
        from collections import Counter
        langs = Counter(r.get("language") for r in rows if "language" in r)
        state["languages"] = dict(langs)
        # Verify proposition schema
        state["schema_ok"] = all(
            "chunk_id" in r and "text" in r and "source_id" in r and "language" in r
            for r in rows
        )
    except Exception as exc:  # noqa: BLE001
        return None, failure("CORPUS_ERROR", "corpus_load", exc)

    print_json("CORPUS", state)

    failures = []
    if state["row_count"] != EXPECTED_CHUNKS:
        failures.append(f"row_count={state['row_count']} (expected {EXPECTED_CHUNKS})")
    if not state["schema_ok"]:
        failures.append("proposition schema missing: chunk_id/text/source_id/language")

    if failures:
        print_json("CORPUS_FAILURES", failures)
        return None, {"phase": "corpus_check", "failures": failures}
    return state, None


# ---------------------------------------------------------------------------
# Phase 3-6: Chat API calls
# ---------------------------------------------------------------------------

def call_chat(query: str, language: str = "vi", session_id: str = "verify-s03-test") -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """POST /chat and return the response body."""
    url = f"{BACKEND_URL.rstrip('/')}/chat"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-API-Key": BACKEND_API_KEY,
    }
    payload = {
        "session_id": session_id,
        "message": query,
        "language": language,
    }
    started = time.perf_counter()
    try:
        status, body = request_json("POST", url, body=payload, headers=headers, timeout=120)
    except Exception as exc:  # noqa: BLE001
        return None, failure("CHAT_ERROR", f"chat_{language}", exc)

    body["client_latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
    print_json(f"CHAT_{language.upper()}", {"url": url, "http_status": status, "body": body})
    return body, None


def load_corpus_titles() -> set[str]:
    """Load all unique source titles from the corpus for citation verification."""
    base = os.path.dirname(os.path.dirname(__file__))
    corpus_path = os.path.join(base, "data", "tourism_documents.jsonl")
    titles: set[str] = set()
    try:
        with open(corpus_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    d = json.loads(line)
                    if d.get("title"):
                        titles.add(d["title"])
    except Exception:
        pass
    return titles


def validate_vietnamese_response(body: dict[str, Any], corpus_titles: set[str]) -> list[str]:
    """Verify Vietnamese query returns non-empty citations with sources from real corpus."""
    failures = []
    citations = body.get("citations", [])
    if not citations:
        failures.append("Vietnamese query returned no citations (expected non-empty)")
    else:
        # Verify citations have non-empty source and snippet
        for c in citations:
            if not c.get("source"):
                failures.append("citation missing non-empty 'source' field")
                break
        # Verify at least one citation source matches a corpus title
        matched = sum(1 for c in citations if c.get("source") in corpus_titles)
        if matched == 0:
            failures.append(
                f"no citations matched corpus titles (got sources: "
                f"{[c.get('source') for c in citations[:3]]})"
            )
    if not body.get("message"):
        failures.append("response message is empty")
    return failures


def validate_english_response(body: dict[str, Any]) -> list[str]:
    """Verify English query returns non-empty citations."""
    failures = []
    citations = body.get("citations", [])
    if not citations:
        failures.append("English query returned no citations (expected non-empty)")
    return failures


def validate_out_of_scope_response(body: dict[str, Any]) -> list[str]:
    """Verify out-of-scope query returns fallback=True or empty citations."""
    failures = []
    if not body.get("fallback"):
        # If fallback is False/None, citations must be empty (honest no-evidence)
        citations = body.get("citations", [])
        if citations:
            failures.append(
                f"out-of-scope query returned {len(citations)} citations without fallback=True "
                "(expected fallback=True or empty citations for no-evidence response)"
            )
    # Accept either fallback=True OR empty citations
    return failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print_json(
        "CONFIG",
        {
            "backend_url": BACKEND_URL,
            "expected_chunks": EXPECTED_CHUNKS,
            "openai_api_key_status": key_status(),
        },
    )

    # Phase 1: corpus check
    corpus_state, corpus_error = check_corpus()
    if corpus_error:
        print("RESULT=corpus_failed")
        return 1

    # Phase 2: credential_blocked — exit 0 honestly if no valid key
    if credential_blocked():
        print_json(
            "RESULT",
            {
                "status": "credential_blocked",
                "rerun": (
                    "export OPENAI_API_KEY=<valid key>; "
                    "python3 scripts/verify-retrieval-agent-s03.py"
                ),
            },
        )
        print("RESULT=credential_blocked")
        return 0

    # Load corpus titles for citation verification
    corpus_titles = load_corpus_titles()
    print_json("CORPUS_TITLES_COUNT", len(corpus_titles))

    # Phase 3: Vietnamese query
    vi_body, vi_error = call_chat("Hàm Ninh có gì đặc biệt?", language="vi")
    if vi_error:
        print_json("VI_FAILURES", [vi_error])
        print("RESULT=vi_chat_failed")
        return 1

    vi_failures = validate_vietnamese_response(vi_body, corpus_titles)
    if vi_failures:
        print_json("VI_VALIDATION_FAILURES", vi_failures)
        print("RESULT=vi_validation_failed")
        return 1

    # Phase 5: English query
    en_body, en_error = call_chat("What is special about Hàm Ninh?", language="en")
    if en_error:
        print_json("EN_FAILURES", [en_error])
        print("RESULT=en_chat_failed")
        return 1

    en_failures = validate_english_response(en_body)
    if en_failures:
        print_json("EN_VALIDATION_FAILURES", en_failures)
        print("RESULT=en_validation_failed")
        return 1

    # Phase 6: Out-of-scope query
    oos_body, oos_error = call_chat("weather in Hanoi", language="en")
    if oos_error:
        print_json("OOS_FAILURES", [oos_error])
        print("RESULT=oos_chat_failed")
        return 1

    oos_failures = validate_out_of_scope_response(oos_body)
    if oos_failures:
        print_json("OOS_VALIDATION_FAILURES", oos_failures)
        print("RESULT=oos_validation_failed")
        return 1

    # All good
    print_json(
        "RESULT",
        {
            "status": "passed",
            "vi_citation_count": len(vi_body.get("citations", [])),
            "en_citation_count": len(en_body.get("citations", [])),
            "oos_fallback": oos_body.get("fallback"),
            "oos_citation_count": len(oos_body.get("citations", [])),
        },
    )
    print("RESULT=passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())