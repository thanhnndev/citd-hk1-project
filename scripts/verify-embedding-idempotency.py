#!/usr/bin/env python3
"""Verify /admin/embed idempotency and Qdrant collection state.

Run from the repository root after exporting a valid OPENAI_API_KEY and ensuring
Qdrant plus the backend API are reachable. The script intentionally prints a
credential-blocked status instead of failing when the OpenAI key is absent/fake,
so milestone validation can distinguish infrastructure readiness from missing
secrets.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

EXPECTED_POINTS = 321
EXPECTED_VECTOR_DIM = 1536
COLLECTION_NAME = os.environ.get("QDRANT_COLLECTION", "tourism_chunks")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:46333")
BACKEND_API_KEY = os.environ.get("BACKEND_API_KEY", "test-admin-key")


def key_status() -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return "missing"
    if key.startswith("fake"):
        return "fake"
    return f"present_prefix_{key[:7]}_len_{len(key)}"


def request_json(method: str, url: str, timeout: int = 120) -> tuple[int, dict]:
    req = urllib.request.Request(url, method=method)
    req.add_header("Accept", "application/json")
    if url.startswith(BACKEND_URL.rstrip("/")):
        req.add_header("X-API-Key", BACKEND_API_KEY)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read().decode("utf-8")
        return response.status, json.loads(data) if data else {}


def qdrant_collection_state() -> dict:
    status, body = request_json(
        "GET", f"{QDRANT_URL.rstrip('/')}/collections/{COLLECTION_NAME}", timeout=10
    )
    result = body.get("result", {})
    vectors = result.get("config", {}).get("params", {}).get("vectors")
    if isinstance(vectors, dict) and "dense" in vectors:
        vector_dim = vectors["dense"].get("size")
    elif isinstance(vectors, dict):
        vector_dim = vectors.get("size")
    else:
        vector_dim = None
    return {
        "http_status": status,
        "points_count": result.get("points_count"),
        "vectors_count": result.get("vectors_count"),
        "vector_dim": vector_dim,
        "vector_config": vectors,
    }


def print_json(label: str, value: object) -> None:
    print(f"{label}={json.dumps(value, sort_keys=True, ensure_ascii=False)}")


def main() -> int:
    print(f"OPENAI_API_KEY_STATUS={key_status()}")
    print(f"BACKEND_URL={BACKEND_URL}")
    print(f"QDRANT_URL={QDRANT_URL}")
    print(f"COLLECTION_NAME={COLLECTION_NAME}")

    try:
        health_status, health_body = request_json("GET", f"{BACKEND_URL.rstrip('/')}/health", timeout=10)
        print_json("BACKEND_HEALTH", {"http_status": health_status, "body": health_body})
    except Exception as exc:  # noqa: BLE001 - diagnostic script should preserve exact failure.
        print(f"BACKEND_HEALTH_ERROR={type(exc).__name__}: {exc}")

    try:
        print_json("QDRANT_COLLECTION_BEFORE", qdrant_collection_state())
    except Exception as exc:  # noqa: BLE001
        print(f"QDRANT_COLLECTION_BEFORE_ERROR={type(exc).__name__}: {exc}")

    if key_status() in {"missing", "fake"}:
        print("RESULT=credential_blocked")
        print("RERUN=export OPENAI_API_KEY=<valid key>; ensure Qdrant/backend are running; python3 scripts/verify-embedding-idempotency.py")
        return 0

    embed_url = f"{BACKEND_URL.rstrip('/')}/admin/embed"
    responses = []
    for run in (1, 2):
        started = time.perf_counter()
        try:
            status, body = request_json("POST", embed_url, timeout=180)
        except urllib.error.HTTPError as exc:
            print(f"EMBED_RUN_{run}_ERROR=HTTPError: {exc.code} {exc.read().decode('utf-8', 'replace')}")
            return 1
        except Exception as exc:  # noqa: BLE001
            print(f"EMBED_RUN_{run}_ERROR={type(exc).__name__}: {exc}")
            return 1
        body["client_latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        responses.append(body)
        print_json(f"EMBED_RUN_{run}", {"http_status": status, "body": body})

    final_state = qdrant_collection_state()
    print_json("QDRANT_COLLECTION_AFTER", final_state)

    failures = []
    for idx, body in enumerate(responses, start=1):
        if body.get("total_chunks") != EXPECTED_POINTS:
            failures.append(f"run {idx} total_chunks={body.get('total_chunks')}")
        if body.get("vector_dim") != EXPECTED_VECTOR_DIM:
            failures.append(f"run {idx} vector_dim={body.get('vector_dim')}")
    if final_state.get("points_count") != EXPECTED_POINTS:
        failures.append(f"points_count={final_state.get('points_count')}")
    if final_state.get("vector_dim") != EXPECTED_VECTOR_DIM:
        failures.append(f"vector_dim={final_state.get('vector_dim')}")

    if failures:
        print("RESULT=failed")
        print("FAILURES=" + "; ".join(failures))
        return 1

    print("RESULT=passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
