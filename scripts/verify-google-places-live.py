#!/usr/bin/env python3
"""Verify live Google Places proof or report credential blocking.

Run from the repository root. The script intentionally exits 0 with
RESULT=credential_blocked for missing/fake/placeholder Google Places keys so
release evidence can distinguish absent credentials from a failed live proof.
It never prints API keys, auth headers, or raw provider payloads.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import Settings  # noqa: E402
from app.models.places import HAM_NINH_CENTER, PlaceCandidate, PlaceSearchRequest, PlaceToolStatus  # noqa: E402
from agents.tools.places_service import GooglePlacesService  # noqa: E402

QUERY = "quán ăn hải sản hoặc điểm dịch vụ du lịch ở Hàm Ninh Phú Quốc"
FAKE_PREFIXES = ("fake", "test", "dummy", "example")
PLACEHOLDER_MARKERS = ("[redacted", "redacted", "xxxx", "<", "your_", "replace_me", "changeme")


def key_status() -> str:
    key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
    lowered = key.lower()
    if not key:
        return "missing"
    if lowered.startswith(FAKE_PREFIXES):
        return "fake"
    if lowered.startswith(PLACEHOLDER_MARKERS) or lowered.endswith((">", "xxxx")):
        return "placeholder"
    return "present"


def credential_blocked() -> bool:
    return key_status() in {"missing", "fake", "placeholder"}


def print_json(label: str, value: object) -> None:
    print(f"{label}={json.dumps(value, sort_keys=True, ensure_ascii=False)}")


def sanitized_candidate(candidate: PlaceCandidate) -> dict[str, Any]:
    location = None
    if candidate.location is not None:
        location = {"lat": round(candidate.location.lat, 6), "lng": round(candidate.location.lng, 6)}
    return {
        "place_id_present": bool(candidate.place_id),
        "display_name": candidate.display_name,
        "primary_type": candidate.primary_type,
        "types": candidate.types[:5],
        "location": location,
        "google_maps_uri_present": bool(candidate.google_maps_uri),
        "rating": candidate.rating,
        "user_rating_count": candidate.user_rating_count,
        "distance_meters": candidate.route_context.distance_meters if candidate.route_context else None,
    }


def validate_candidates(candidates: list[PlaceCandidate]) -> list[str]:
    if not candidates:
        return ["no normalized candidates returned"]

    failures: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        if not candidate.place_id:
            failures.append(f"candidate_{index}: missing place_id")
        if not candidate.display_name:
            failures.append(f"candidate_{index}: missing display_name")
        if candidate.location is None and not candidate.google_maps_uri:
            failures.append(f"candidate_{index}: missing location_or_google_maps_uri")
    return failures


def settings_for_places() -> Settings:
    return Settings(
        OPENAI_API_KEY=os.environ.get("OPENAI_API_KEY", "unused-for-places-live-verifier"),
        GOOGLE_PLACES_API_KEY=os.environ.get("GOOGLE_PLACES_API_KEY", ""),
    )


async def verify_live_places() -> int:
    status = key_status()
    print_json(
        "CONFIG",
        {
            "google_places_api_key_status": status,
            "query_language": "vi",
            "location_bias": {"lat": HAM_NINH_CENTER.lat, "lng": HAM_NINH_CENTER.lng},
            "max_result_count": 5,
        },
    )

    if credential_blocked():
        print_json(
            "RESULT",
            {
                "status": "credential_blocked",
                "rerun": "export GOOGLE_PLACES_API_KEY=<valid key>; python3 scripts/verify-google-places-live.py",
            },
        )
        print("RESULT=credential_blocked")
        return 0

    service = GooglePlacesService(settings=settings_for_places())
    request = PlaceSearchRequest(
        query=QUERY,
        language_code="vi",
        location_bias=HAM_NINH_CENTER,
        radius_meters=8_000,
        max_result_count=5,
    )

    try:
        response = await service.text_search(request)
    except Exception as exc:  # noqa: BLE001 - operational verifier must sanitize import/client failures.
        print_json("ERROR", {"phase": "text_search", "error_type": type(exc).__name__, "message": str(exc)[:240]})
        print_json("RESULT", {"status": "failed", "reason": "exception"})
        print("RESULT=failed")
        return 1
    finally:
        client = getattr(service, "_client", None)
        close = getattr(client, "aclose", None)
        if close is not None:
            await close()

    validation_failures = validate_candidates(response.candidates) if response.status == PlaceToolStatus.OK else []
    print_json(
        "PLACES_RESPONSE",
        {
            "status": response.status.value,
            "source": response.source.value,
            "candidate_count": len(response.candidates),
            "error": response.error.model_dump(mode="json") if response.error else None,
            "field_mask_present": bool(response.metadata.get("field_mask")),
        },
    )
    print_json("CANDIDATES", [sanitized_candidate(candidate) for candidate in response.candidates[:5]])

    if response.status != PlaceToolStatus.OK:
        print_json("RESULT", {"status": "failed", "reason": f"places_status_{response.status.value}"})
        print("RESULT=failed")
        return 1
    if validation_failures:
        print_json("VALIDATION_ERRORS", validation_failures)
        print_json("RESULT", {"status": "failed", "reason": "candidate_validation"})
        print("RESULT=failed")
        return 1

    print_json("RESULT", {"status": "passed", "candidate_count": len(response.candidates)})
    print("RESULT=passed")
    return 0


def main() -> int:
    return asyncio.run(verify_live_places())


if __name__ == "__main__":
    raise SystemExit(main())
