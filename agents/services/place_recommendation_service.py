"""Deterministic place recommendation seam grounded in Places tool output."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote

from pydantic import ValidationError

from app.models.places import (
    DEFAULT_SEARCH_RADIUS_METERS,
    HAM_NINH_CENTER,
    PlaceCandidate,
    PlaceSearchRequest,
    PlaceToolResponse,
    PlaceToolSource,
    PlaceToolStatus,
)
from app.models.request import LatLng
from app.models.response import ChatResponse, PlaceResult, ScoreBreakdown
from agents.ml.ensemble_reranker import EnsembleReranker
from agents.ml.feature_extractor import FeatureExtractor
from agents.tools.places_service import GoongPlacesService
from agents.tools.routes_service import GoongRoutesService

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = 10
PLACE_RECOMMENDATION_INTENT = "place_recommendation"


class TextSearchPlacesTool(Protocol):
    """Places dependency required by the recommendation service."""

    async def text_search(self, request: PlaceSearchRequest) -> PlaceToolResponse: ...


class RoutesServiceProtocol(Protocol):
    """Optional routes dependency for enriching candidates with real driving distances."""

    async def enrich_candidates(
        self, candidates: list[PlaceCandidate], origin: LatLng
    ) -> list[PlaceCandidate]: ...


class PlaceRecommendationService:
    """Build ChatResponse place recommendations that cannot invent place ids."""

    def __init__(
        self,
        places_tool: TextSearchPlacesTool | None = None,
        *,
        max_result_count: int = DEFAULT_MAX_RESULTS,
        routes_service: RoutesServiceProtocol | None = None,
    ) -> None:
        self._places_tool = places_tool or GoongPlacesService()
        self._max_result_count = max(1, min(max_result_count, 20))
        self._routes_service = routes_service if routes_service is not None else GoongRoutesService()

    async def recommend(self, *, query: str, language: str = "vi", session_id: str) -> ChatResponse:
        started = time.perf_counter()
        try:
            request = self._build_request(query=query, language=language)
        except ValidationError:
            return self._chat_response(
                session_id=session_id,
                message=_message_for_status(PlaceToolStatus.INVALID_REQUEST),
                status=PlaceToolStatus.INVALID_REQUEST,
                source=None,
                candidate_count=0,
                places=[],
                latency_ms=_elapsed_ms(started),
                fallback=True,
            )

        try:
            tool_response = await self._places_tool.text_search(request)
        except Exception as exc:  # noqa: BLE001 - service boundary must fail closed and sanitize.
            logger.warning("place_recommendation_tool_error", extra={"error_type": type(exc).__name__})
            return self._chat_response(
                session_id=session_id,
                message=_message_for_status(PlaceToolStatus.UPSTREAM_ERROR),
                status=PlaceToolStatus.UPSTREAM_ERROR,
                source=None,
                candidate_count=0,
                places=[],
                latency_ms=_elapsed_ms(started),
                fallback=True,
            )

        candidate_count = len(tool_response.candidates)
        if tool_response.status != PlaceToolStatus.OK:
            logger.info(
                "place_recommendation_status",
                extra={"status": tool_response.status.value, "source": tool_response.source.value, "candidate_count": candidate_count, "result_count": 0},
            )
            return self._chat_response(
                session_id=session_id,
                message=_message_for_status(tool_response.status),
                status=tool_response.status,
                source=tool_response.source,
                candidate_count=candidate_count,
                places=[],
                latency_ms=_elapsed_ms(started),
                fallback=tool_response.status != PlaceToolStatus.EMPTY,
            )

        # Route enrichment (optional — degrades gracefully)
        candidates = tool_response.candidates
        try:
            if self._routes_service is not None:
                candidates = await self._routes_service.enrich_candidates(
                    tool_response.candidates, origin=request.location_bias
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("route_enrichment_failed", extra={"error_type": type(exc).__name__})
            candidates = tool_response.candidates

        try:
            places = _reranked_results(candidates, request.query)
        except Exception as exc:  # noqa: BLE001 - ensemble pipeline fails closed.
            logger.warning("ensemble_reranking_failed", extra={"error_type": type(exc).__name__})
            places = _grounded_results(candidates)

        logger.info(
            "place_recommendation_status",
            extra={"status": tool_response.status.value, "source": tool_response.source.value, "candidate_count": candidate_count, "result_count": len(places)},
        )
        return self._chat_response(
            session_id=session_id,
            message=_message_for_status(tool_response.status, result_count=len(places)),
            status=tool_response.status,
            source=tool_response.source,
            candidate_count=candidate_count,
            places=places,
            latency_ms=_elapsed_ms(started),
            fallback=False,
        )

    def _build_request(self, *, query: str, language: str) -> PlaceSearchRequest:
        language_code = language if language in {"vi", "en"} else "vi"
        return PlaceSearchRequest(
            query=query,
            language_code=language_code,
            location_bias=HAM_NINH_CENTER.model_copy(),
            radius_meters=DEFAULT_SEARCH_RADIUS_METERS,
            max_result_count=self._max_result_count,
        )

    def _chat_response(
        self,
        *,
        session_id: str,
        message: str,
        status: PlaceToolStatus,
        source: PlaceToolSource | None,
        candidate_count: int,
        places: list[PlaceResult],
        latency_ms: float,
        fallback: bool,
    ) -> ChatResponse:
        source_value = source.value if source else "none"
        reasoning_log = f"place_recommendation status={status.value} source={source_value} candidate_count={candidate_count} result_count={len(places)}"
        return ChatResponse(
            session_id=session_id,
            message=message,
            citations=[],
            places=places,
            reasoning_log=reasoning_log,
            intent=PLACE_RECOMMENDATION_INTENT,
            latency_ms=latency_ms,
            fallback=fallback,
        )


def _reranked_results(
    candidates: list[PlaceCandidate], query: str
) -> list[PlaceResult]:
    """Run candidates through FeatureExtractor → EnsembleReranker pipeline."""
    extractor = FeatureExtractor()
    feature_dicts = [
        extractor.extract(candidate, query, user_location=None)
        for candidate in candidates
    ]

    sorted_candidates, score_breakdowns = EnsembleReranker().rerank(
        candidates, feature_dicts
    )

    results: list[PlaceResult] = []
    for candidate, breakdown in zip(sorted_candidates, score_breakdowns):
        accessibility_score = candidate.accessibility_score
        if accessibility_score is None and candidate.accessibility_options:
            accessibility_score = (
                1.0 if any(candidate.accessibility_options.values()) else 0.0
            )

        results.append(
            PlaceResult(
                place_id=candidate.place_id,
                display_name=candidate.display_name,
                formatted_address=candidate.formatted_address
                or candidate.short_formatted_address,
                location=candidate.location,
                types=candidate.types,
                primary_type=candidate.primary_type,
                rating=candidate.rating,
                user_rating_count=candidate.user_rating_count,
                price_level=candidate.price_level,
                open_now=candidate.open_now,
                business_status=candidate.business_status,
                local_factor=candidate.local_factor
                if candidate.local_factor is not None
                else 0.5,
                final_score=breakdown.final_score,
                score_breakdown=breakdown,
                accessibility_score=accessibility_score,
                accessibility_warning=candidate.accessibility_warning,
                map_uri=candidate.map_uri
                or _maps_url(candidate.place_id),
            )
        )

    return results


def _grounded_results(candidates: list[PlaceCandidate]) -> list[PlaceResult]:
    """Fallback path: return candidates with default ensemble ScoreBreakdown."""
    results: list[PlaceResult] = []
    for i, candidate in enumerate(candidates):
        accessibility_score = candidate.accessibility_score
        if accessibility_score is None and candidate.accessibility_options:
            accessibility_score = (
                1.0 if any(candidate.accessibility_options.values()) else 0.0
            )

        results.append(
            PlaceResult(
                place_id=candidate.place_id,
                display_name=candidate.display_name,
                formatted_address=candidate.formatted_address
                or candidate.short_formatted_address,
                location=candidate.location,
                types=candidate.types,
                primary_type=candidate.primary_type,
                rating=candidate.rating,
                user_rating_count=candidate.user_rating_count,
                price_level=candidate.price_level,
                open_now=candidate.open_now,
                business_status=candidate.business_status,
                local_factor=candidate.local_factor
                if candidate.local_factor is not None
                else 0.5,
                final_score=0.5,
                score_breakdown=ScoreBreakdown(
                    tree1_locality=0.5,
                    tree2_proximity=0.5,
                    tree3_quality=0.5,
                    s_bag=0.5,
                    delta1_fairness=0.0,
                    delta2_access=0.0,
                    final_score=0.5,
                    rank=i + 1,
                ),
                accessibility_score=accessibility_score,
                accessibility_warning=candidate.accessibility_warning,
                map_uri=candidate.map_uri
                or _maps_url(candidate.place_id),
            )
        )

    return results


def _maps_url(place_id: str) -> str:
    return f"https://map.goong.io/?pid={quote(place_id, safe='')}"


def _message_for_status(status: PlaceToolStatus, *, result_count: int = 0) -> str:
    if status == PlaceToolStatus.OK:
        return f"I found {result_count} Ham Ninh place option(s) from Goong Places."
    if status == PlaceToolStatus.EMPTY:
        return "I could not find matching Ham Ninh places from Goong Places for that request."
    if status == PlaceToolStatus.CREDENTIALS_BLOCKED:
        return "Place recommendations are unavailable because the server Places credentials are not configured."
    if status == PlaceToolStatus.UPSTREAM_ERROR:
        return "Place recommendations are temporarily unavailable because Goong Places could not be reached. Please try again shortly."
    if status == PlaceToolStatus.INVALID_REQUEST:
        return "I could not search for places because the request was invalid. Please try a shorter Ham Ninh place request."
    return "Place recommendations are unavailable right now. Please try again later."


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
