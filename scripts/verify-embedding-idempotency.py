#!/usr/bin/env python3
"""Verify /admin/embed idempotency and Qdrant named-vector state.

Run from the repository root after exporting a valid OPENAI_API_KEY and ensuring
Qdrant plus the backend API are reachable. The milestone backend usually listens
on http://localhost:48721; override BACKEND_URL when using a different port.
The script intentionally prints a credential-blocked status instead of failing
when the OpenAI key is absent/fake, so validation can distinguish readiness from
missing secrets.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

EXPECTED_POINTS = 321
EXPECTED_VECTOR_DIM = 1536
DENSE_VECTOR_NAME = "dense"
COLLECTION_NAME = os.environ.get("QDRANT_COLLECTION", "tourism_chunks")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:48721")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:46333")
BACKEND_API_KEY = os.environ.get("BACKEND_API_KEY", "test-admin-key")


def key_status() -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return "missing"
    if key.startswith("fake"):
        return "fake"
    return f"present_prefix_{key[:7]}_len_{len(key)}"


def credential_blocked() -> bool:
    return key_status() in {"missing", "fake"}


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
        payload: dict[str, Any] = {"phase": phase, "error_type": "HTTPError", "http_status": exc.code, "body": body}
    elif isinstance(exc, urllib.error.URLError):
        payload = {"phase": phase, "error_type": type(exc).__name__, "message": str(exc.reason)}
    elif isinstance(exc, BaseException):
        payload = {"phase": phase, "error_type": type(exc).__name__, "message": str(exc)}
    else:
        payload = {"phase": phase, "error_type": "ValidationError", "message": exc}
    print_json(label, payload)
    return payload


def qdrant_collection_state(label: str) -> dict[str, Any]:
    status, body = request_json(
        "GET", f"{QDRANT_URL.rstrip('/')}/collections/{COLLECTION_NAME}", timeout=10
    )
    result = body.get("result", {})
    if not isinstance(result, dict):
        raise ValueError("Qdrant response result is not an object")

    vectors = result.get("config", {}).get("params", {}).get("vectors")
    dense_config = vectors.get(DENSE_VECTOR_NAME) if isinstance(vectors, dict) else None
    named_dense_present = isinstance(dense_config, dict)
    dense_size = dense_config.get("size") if named_dense_present else None

    state = {
        "label": label,
        "backend_url": BACKEND_URL,
        "qdrant_url": QDRANT_URL,
        "collection_name": COLLECTION_NAME,
        "http_status": status,
        "points_count": result.get("points_count"),
        "vectors_count": result.get("vectors_count"),
        "indexed_vectors_count": result.get("indexed_vectors_count"),
        "dense_vector_name": DENSE_VECTOR_NAME,
        "named_dense_present": named_dense_present,
        "dense_vector_size": dense_size,
        "dense_vector_distance": dense_config.get("distance") if named_dense_present else None,
        "vector_config": vectors,
    }
    return state


def emit_qdrant_state(label: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        state = qdrant_collection_state(label)
    except Exception as exc:  # noqa: BLE001 - diagnostic script should preserve exact failure.
        return None, failure(f"QDRANT_{label}_ERROR", f"qdrant_{label.lower()}", exc)
    print_json(f"QDRANT_{label}", state)
    return state, None


def emit_backend_health() -> dict[str, Any] | None:
    try:
        status, body = request_json("GET", f"{BACKEND_URL.rstrip('/')}/health", timeout=10)
    except Exception as exc:  # noqa: BLE001
        return failure("BACKEND_HEALTH_ERROR", "backend_health", exc)
    print_json("BACKEND_HEALTH", {"backend_url": BACKEND_URL, "http_status": status, "body": body})
    return None


def emit_embed_run(run: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    embed_url = f"{BACKEND_URL.rstrip('/')}/admin/embed"
    started = time.perf_counter()
    try:
        status, body = request_json("POST", embed_url, timeout=300)
    except Exception as exc:  # noqa: BLE001
        return None, failure(f"EMBED_RUN_{run}_ERROR", f"embed_run_{run}", exc)

    body["client_latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
    payload = {"backend_url": BACKEND_URL, "http_status": status, "body": body}
    print_json(f"EMBED_RUN_{run}", payload)
    return payload, None


def validate_state(state: dict[str, Any] | None, label: str) -> list[str]:
    if state is None:
        return [f"{label}: missing qdrant state"]
    failures = []
    if not state.get("named_dense_present"):
        failures.append(f"{label}: named dense vector '{DENSE_VECTOR_NAME}' missing")
    if state.get("dense_vector_size") != EXPECTED_VECTOR_DIM:
        failures.append(f"{label}: dense_vector_size={state.get('dense_vector_size')}")
    if state.get("points_count") != EXPECTED_POINTS:
        failures.append(f"{label}: points_count={state.get('points_count')}")
    return failures


def main() -> int:
    print_json(
        "CONFIG",
        {
            "backend_url": BACKEND_URL,
            "qdrant_url": QDRANT_URL,
            "collection_name": COLLECTION_NAME,
            "expected_points": EXPECTED_POINTS,
            "expected_vector_dim": EXPECTED_VECTOR_DIM,
            "openai_api_key_status": key_status(),
        },
    )

    backend_error = emit_backend_health()
    before_state, before_error = emit_qdrant_state("BEFORE")

    if credential_blocked():
        print_json(
            "RESULT",
            {
                "status": "credential_blocked",
                "rerun": "export OPENAI_API_KEY=<valid key>; ensure Qdrant/backend are running; python3 scripts/verify-embedding-idempotency.py",
            },
        )
        print("RESULT=credential_blocked")
        return 0

    if backend_error or before_error:
        print_json("FAILURES", [err for err in (backend_error, before_error) if err])
        print("RESULT=failed")
        return 1

    run1, run1_error = emit_embed_run(1)
    after_run1, after_run1_error = emit_qdrant_state("AFTER_RUN_1")
    run2, run2_error = emit_embed_run(2) if run1_error is None else (None, None)
    final_state, final_error = emit_qdrant_state("AFTER_RUN_2_FINAL")

    failures: list[str | dict[str, Any]] = [
        err for err in (run1_error, after_run1_error, run2_error, final_error) if err
    ]
    for idx, run in ((1, run1), (2, run2)):
        body = (run or {}).get("body", {})
        if body.get("total_chunks") != EXPECTED_POINTS:
            failures.append(f"run {idx}: total_chunks={body.get('total_chunks')}")
        if body.get("vector_dim") != EXPECTED_VECTOR_DIM:
            failures.append(f"run {idx}: vector_dim={body.get('vector_dim')}")

    failures.extend(validate_state(after_run1, "after_run_1"))
    failures.extend(validate_state(final_state, "after_run_2_final"))
    if after_run1 and final_state and final_state.get("points_count") != after_run1.get("points_count"):
        failures.append(
            f"idempotency: points grew from {after_run1.get('points_count')} to {final_state.get('points_count')}"
        )
    if before_state and before_state.get("points_count") is not None:
        print_json(
            "POINT_COUNT_TRANSITION",
            {
                "before": before_state.get("points_count"),
                "after_run_1": (after_run1 or {}).get("points_count"),
                "after_run_2_final": (final_state or {}).get("points_count"),
            },
        )

    if failures:
        print_json("FAILURES", failures)
        print("RESULT=failed")
        return 1

    print_json("RESULT", {"status": "passed", "points_count": EXPECTED_POINTS, "dense_vector_size": EXPECTED_VECTOR_DIM})
    print("RESULT=passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
