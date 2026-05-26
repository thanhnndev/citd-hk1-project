#!/usr/bin/env python3
"""Verify S02 embed pipeline: corpus + /admin/embed + Qdrant state.

Run from the repository root:
    python3 scripts/verify-embed-pipeline-s02.py

Behaviour:
  - On credential_blocked (no valid OPENAI_API_KEY): exits 0, prints RESULT=credential_blocked.
    This is honest — the script documents that live embedding was NOT verified.
  - On success: verifies stats response has total_chunks=607, vector_dim=1536,
    collection_name=tourism_chunks; runs a Qdrant collection_info check.
  - Exits 1 if any check fails (including Qdrant unavailable).

Follows the M004/S07 pattern: single validation surface for S02 closeout.
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
EXPECTED_VECTOR_DIM = 1536
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
COLLECTION_NAME = os.environ.get("QDRANT_COLLECTION", "tourism_chunks")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:48721")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:46333")
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


def request_json(method: str, url: str, timeout: int = 120) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url, method=method)
    req.add_header("Accept", "application/json")
    if url.startswith(BACKEND_URL.rstrip("/")):
        req.add_header("X-API-Key", BACKEND_API_KEY)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read().decode("utf-8")
        try:
            body = json.loads(data) if data else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed JSON from {url}: {exc}") from exc
        if not isinstance(body, dict):
            raise ValueError(f"expected JSON object from {url}, got {type(body).__name__}")
        return response.status, body


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
# Corpus check
# ---------------------------------------------------------------------------

def check_corpus() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Verify data/tourism_documents.jsonl exists with 607 proposition rows."""
    corpus_path = os.path.join(os.path.dirname(__file__), "..", "data", "tourism_documents.jsonl")
    if not os.path.isabs(corpus_path):
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
        if rows:
            state["languages"] = {}
            from collections import Counter
            langs = Counter(r.get("language") for r in rows if "language" in r)
            state["languages"] = dict(langs)
            # Verify proposition schema
            state["schema_ok"] = all(
                "chunk_id" in r and "text" in r and "source_id" in r
                for r in rows
            )
    except Exception as exc:  # noqa: BLE001
        return None, failure("CORPUS_ERROR", "corpus_load", exc)

    print_json("CORPUS", state)

    failures = []
    if state["row_count"] != EXPECTED_CHUNKS:
        failures.append(
            f"row_count={state['row_count']} (expected {EXPECTED_CHUNKS})"
        )
    if not state["schema_ok"]:
        failures.append("proposition schema missing: chunk_id/text/source_id")

    if failures:
        print_json("CORPUS_FAILURES", failures)
        return None, {"phase": "corpus_check", "failures": failures}
    return state, None


# ---------------------------------------------------------------------------
# Qdrant state check
# ---------------------------------------------------------------------------

def qdrant_collection_state() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Fetch Qdrant collection config and return structured state."""
    try:
        status, body = request_json(
            "GET",
            f"{QDRANT_URL.rstrip('/')}/collections/{COLLECTION_NAME}",
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        return None, failure("QDRANT_STATE_ERROR", "qdrant_collection", exc)

    result = body.get("result", {})
    if not isinstance(result, dict):
        return None, failure(
            "QDRANT_STATE_ERROR", "qdrant_result_type",
            f"expected dict, got {type(result).__name__}",
        )

    vectors = result.get("config", {}).get("params", {}).get("vectors")

    # Dense config
    dense_cfg = vectors.get(DENSE_VECTOR_NAME) if isinstance(vectors, dict) else None
    dense_present = isinstance(dense_cfg, dict)

    # Sparse config
    sparse_cfg = vectors.get(SPARSE_VECTOR_NAME) if isinstance(vectors, dict) else None
    sparse_present = isinstance(sparse_cfg, dict)

    state = {
        "collection_name": COLLECTION_NAME,
        "qdrant_url": QDRANT_URL,
        "http_status": status,
        "points_count": result.get("points_count"),
        "vectors_count": result.get("vectors_count"),
        "indexed_vectors_count": result.get("indexed_vectors_count"),
        "dense_vector_name": DENSE_VECTOR_NAME,
        "dense_vector_present": dense_present,
        "dense_vector_size": dense_cfg.get("size") if dense_present else None,
        "dense_vector_distance": dense_cfg.get("distance") if dense_present else None,
        "sparse_vector_name": SPARSE_VECTOR_NAME,
        "sparse_vector_present": sparse_present,
        "vector_config": dict(vectors) if isinstance(vectors, dict) else None,
    }
    print_json("QDRANT_STATE", state)
    return state, None


# ---------------------------------------------------------------------------
# Backend embed call
# ---------------------------------------------------------------------------

def call_embed() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Call POST /admin/embed and return response body."""
    embed_url = f"{BACKEND_URL.rstrip('/')}/admin/embed"
    started = time.perf_counter()
    try:
        status, body = request_json("POST", embed_url, timeout=300)
    except Exception as exc:  # noqa: BLE001
        return None, failure("EMBED_ERROR", "admin_embed", exc)

    body["client_latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
    payload = {"backend_url": BACKEND_URL, "http_status": status, "body": body}
    print_json("EMBED_CALL", payload)
    return payload, None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_embed_response(embed_body: dict[str, Any]) -> list[str]:
    """Validate the /admin/embed response body against expected values."""
    failures = []
    if embed_body.get("total_chunks") != EXPECTED_CHUNKS:
        failures.append(
            f"total_chunks={embed_body.get('total_chunks')} "
            f"(expected {EXPECTED_CHUNKS})"
        )
    if embed_body.get("vector_dim") != EXPECTED_VECTOR_DIM:
        failures.append(
            f"vector_dim={embed_body.get('vector_dim')} "
            f"(expected {EXPECTED_VECTOR_DIM})"
        )
    if embed_body.get("collection_name") != COLLECTION_NAME:
        failures.append(
            f"collection_name={embed_body.get('collection_name')} "
            f"(expected {COLLECTION_NAME})"
        )
    if embed_body.get("propositions_ingested") != EXPECTED_CHUNKS:
        failures.append(
            f"propositions_ingested={embed_body.get('propositions_ingested')} "
            f"(expected {EXPECTED_CHUNKS})"
        )
    if "latency_ms" not in embed_body:
        failures.append("latency_ms field missing from response")
    return failures


def validate_qdrant_state(state: dict[str, Any]) -> list[str]:
    """Validate Qdrant collection state."""
    failures = []
    if not state.get("dense_vector_present"):
        failures.append(f"dense vector '{DENSE_VECTOR_NAME}' not present in config")
    if state.get("dense_vector_size") != EXPECTED_VECTOR_DIM:
        failures.append(
            f"dense_vector_size={state.get('dense_vector_size')} "
            f"(expected {EXPECTED_VECTOR_DIM})"
        )
    if state.get("sparse_vector_present") != True:
        failures.append(
            f"sparse vector '{SPARSE_VECTOR_NAME}' not present "
            f"(expected present for hybrid pipeline)"
        )
    if state.get("points_count") != EXPECTED_CHUNKS:
        failures.append(
            f"points_count={state.get('points_count')} "
            f"(expected {EXPECTED_CHUNKS})"
        )
    return failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print_json(
        "CONFIG",
        {
            "backend_url": BACKEND_URL,
            "qdrant_url": QDRANT_URL,
            "collection_name": COLLECTION_NAME,
            "expected_chunks": EXPECTED_CHUNKS,
            "expected_vector_dim": EXPECTED_VECTOR_DIM,
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
                    "python3 scripts/verify-embed-pipeline-s02.py"
                ),
            },
        )
        print("RESULT=credential_blocked")
        return 0

    # Phase 3: Qdrant state (before embed)
    qdrant_before, qdrant_before_error = qdrant_collection_state()

    # Phase 4: /admin/embed call
    embed_result, embed_error = call_embed()
    if embed_error:
        print_json("EMBED_FAILURES", [embed_error])
        print("RESULT=embed_failed")
        return 1

    # Phase 5: validate embed response
    embed_failures = validate_embed_response(embed_result.get("body", {}))
    if embed_failures:
        print_json("EMBED_RESPONSE_FAILURES", embed_failures)
        print("RESULT=embed_response_invalid")
        return 1

    # Phase 6: Qdrant state (after embed)
    qdrant_after, qdrant_after_error = qdrant_collection_state()

    # Phase 7: validate Qdrant state
    qdrant_failures = []
    if qdrant_after_error:
        qdrant_failures.append(str(qdrant_after_error))
    elif qdrant_after:
        qdrant_failures.extend(validate_qdrant_state(qdrant_after))

    if qdrant_failures:
        print_json("QDRANT_VALIDATION_FAILURES", qdrant_failures)
        print("RESULT=qdrant_validation_failed")
        return 1

    # All good
    print_json(
        "RESULT",
        {
            "status": "passed",
            "total_chunks": EXPECTED_CHUNKS,
            "vector_dim": EXPECTED_VECTOR_DIM,
            "collection_name": COLLECTION_NAME,
        },
    )
    print("RESULT=passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())