#!/usr/bin/env python3
"""Verify live Goong Places and Routes proof or report credential blocking.

Run from the repository root. Missing/fake/placeholder GOONG_API_KEY values exit 0
with RESULT=credential_blocked so release evidence never confuses absent
credentials with provider success. Output is phase-labeled, sanitized, and never
prints API keys or raw upstream payloads.
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
for path in (REPO_ROOT, BACKEND_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agents.tools.places_service import GooglePlacesService  # noqa: E402
from agents.tools.routes_service import GoongRoutesService  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.models.places import HAM_NINH_CENTER, PlaceCandidate, PlaceSearchRequest, PlaceToolStatus  # noqa: E402
from app.models.request import LatLng  # noqa: E402

QUERY = "quan an hai san hoac diem dich vu du lich o Ham Ninh Phu Quoc"
MAX_ROUTE_DESTINATIONS = 3
FAKE_PREFIXES = ("fake", "test", "dummy", "example")
PLACEHOLDER_MARKERS = ("[redacted", "redacted", "xxxx", "<", "your_", "replace_me", "changeme")


def key_status() -> str:
    key = os.environ.get("GOONG_API_KEY", "").strip()
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
    print(f"{label}={json.dumps(value, sort_keys=True, ensure_ascii=True)}")


def settings_for_google() -> Settings:
    return Settings(
        OPENAI_API_KEY=os.environ.get("OPENAI_API_KEY", "unused-for-places-live-verifier"),
        GOONG_API_KEY=os.environ.get("GOONG_API_KEY", ""),
    )


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
        "rating": candidate.rating,
        "user_rating_count": candidate.user_rating_count,
    }


def validate_candidates(candidates: list[PlaceCandidate]) -> tuple[list[str], list[LatLng]]:
    failures: list[str] = []
    destinations: list[LatLng] = []
    if not candidates:
        return ["no normalized candidates returned"], destinations

    for index, candidate in enumerate(candidates, start=1):
        if not candidate.place_id:
            failures.append(f"candidate_{index}: missing place_id")
        if not candidate.display_name:
            failures.append(f"candidate_{index}: missing display_name")
        if candidate.location is None:
            failures.append(f"candidate_{index}: missing coordinates")
        else:
            destinations.append(candidate.location)
    return failures, destinations


async def close_service_client(service: object) -> None:
    client = getattr(service, "_client", None)
    close = getattr(client, "aclose", None)
    if close is not None:
        await close()


def route_successes(results: list[dict[str, Any]]) -> int:
    return sum(
        1
        for result in results
        if isinstance(result, dict)
        and result.get("status") in (None, "OK")
        and (result.get("distanceMeters") is not None or result.get("durationSeconds") is not None)
    )


async def verify_live_goong() -> int:
    status = key_status()
    print_json(
        "CONFIG",
        {
            "google_places_api_key_status": status,
            "query_language": "vi",
            "location_bias": {"lat": HAM_NINH_CENTER.lat, "lng": HAM_NINH_CENTER.lng},
            "max_places_result_count": 5,
            "max_route_destinations": MAX_ROUTE_DESTINATIONS,
        },
    )

    if credential_blocked():
        print_json(
            "RESULT",
            {
                "status": "credential_blocked",
                "rerun": "export GOONG_API_KEY=<valid key>; python3 scripts/verify-goong-live.py",
            },
        )
        print("RESULT=credential_blocked")
        return 0

    settings = settings_for_google()
    places_service = GooglePlacesService(settings=settings)
    routes_service = GoongRoutesService(settings=settings)
    try:
        request = PlaceSearchRequest(
            query=QUERY,
            language_code="vi",
            location_bias=HAM_NINH_CENTER,
            radius_meters=8_000,
            max_result_count=5,
        )
        places_response = await places_service.text_search(request)
    except Exception as exc:  # noqa: BLE001 - operational verifier must sanitize service/client failures.
        print_json("ERROR", {"phase": "text_search", "error_type": type(exc).__name__, "message": str(exc)[:240]})
        print_json("RESULT", {"status": "failed", "reason": "places_exception"})
        print("RESULT=failed")
        await close_service_client(places_service)
        await close_service_client(routes_service)
        return 1

    print_json(
        "PLACES_RESPONSE",
        {
            "status": places_response.status.value,
            "source": places_response.source.value,
            "candidate_count": len(places_response.candidates),
            "error": places_response.error.model_dump(mode="json") if places_response.error else None,
        },
    )
    print_json("CANDIDATES", [sanitized_candidate(candidate) for candidate in places_response.candidates[:5]])

    failures, destinations = validate_candidates(places_response.candidates)
    if places_response.status != PlaceToolStatus.OK:
        await close_service_client(places_service)
        await close_service_client(routes_service)
        print_json("RESULT", {"status": "failed", "reason": f"places_status_{places_response.status.value}"})
        print("RESULT=failed")
        return 1
    if failures:
        await close_service_client(places_service)
        await close_service_client(routes_service)
        print_json("VALIDATION_ERRORS", failures)
        print_json("RESULT", {"status": "failed", "reason": "candidate_validation"})
        print("RESULT=failed")
        return 1

    route_destinations = destinations[:MAX_ROUTE_DESTINATIONS]
    try:
        route_results = await routes_service.computeRouteMatrix(HAM_NINH_CENTER, route_destinations)
    except Exception as exc:  # noqa: BLE001 - keep diagnostics sanitized.
        print_json("ERROR", {"phase": "compute_route_matrix", "error_type": type(exc).__name__, "message": str(exc)[:240]})
        print_json("RESULT", {"status": "failed", "reason": "routes_exception"})
        print("RESULT=failed")
        await close_service_client(places_service)
        await close_service_client(routes_service)
        return 1
    finally:
        await close_service_client(places_service)
        await close_service_client(routes_service)

    successes = route_successes(route_results)
    print_json(
        "ROUTES_RESPONSE",
        {
            "destination_count": len(route_destinations),
            "result_count": len(route_results),
            "success_count": successes,
            "statuses": [str(result.get("status", ""))[:40] for result in route_results if isinstance(result, dict)],
        },
    )
    if len(route_results) < len(route_destinations) or successes == 0:
        print_json("RESULT", {"status": "failed", "reason": "route_validation"})
        print("RESULT=failed")
        return 1

    print_json(
        "RESULT",
        {
            "status": "passed",
            "candidate_count": len(places_response.candidates),
            "route_destination_count": len(route_destinations),
            "route_success_count": successes,
        },
    )
    print("RESULT=passed")
    return 0


def main() -> int:
    return asyncio.run(verify_live_goong())


if __name__ == "__main__":
    raise SystemExit(main())
