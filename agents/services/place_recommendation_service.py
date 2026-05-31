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
    FairnessAudit,
    FairnessWarningType,
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
from agents.tools.places_service import GooglePlacesService
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
        self._places_tool = places_tool or GooglePlacesService()
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
                fairness_audit=FairnessAudit(
                    candidate_count=0,
                    result_count=0,
                    provider_status=PlaceToolStatus.INVALID_REQUEST.value,
                    warnings=[FairnessWarningType.PROVIDER_NON_OK.value],
                ),
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
                fairness_audit=FairnessAudit(
                    candidate_count=0,
                    result_count=0,
                    provider_status=PlaceToolStatus.UPSTREAM_ERROR.value,
                    warnings=[FairnessWarningType.PROVIDER_NON_OK.value],
                ),
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
                fairness_audit=FairnessAudit(
                    candidate_count=candidate_count,
                    result_count=0,
                    provider_status=tool_response.status.value,
                    warnings=[FairnessWarningType.PROVIDER_NON_OK.value],
                ),
            )

        # Route enrichment (optional — degrades gracefully)
        candidates = tool_response.candidates
        route_enrichment_ok = True
        try:
            if self._routes_service is not None:
                candidates = await self._routes_service.enrich_candidates(
                    tool_response.candidates, origin=request.location_bias
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("route_enrichment_failed", extra={"error_type": type(exc).__name__})
            candidates = tool_response.candidates
            route_enrichment_ok = False

        ensemble_ok = True
        try:
            places = _reranked_results(candidates, request.query)
        except Exception as exc:  # noqa: BLE001 - ensemble pipeline fails closed.
            logger.warning("ensemble_reranking_failed", extra={"error_type": type(exc).__name__})
            places = _grounded_results(candidates)
            ensemble_ok = False

        # Fairness balancing: reorder results so top-K local representation
        # meets the 40% target when enough local candidates exist.
        places = _balance_fairness(places)

        fairness_audit = _compute_fairness_audit(
            candidates=candidates,
            results=places,
            provider_status=tool_response.status,
            route_enrichment_ok=route_enrichment_ok,
            ensemble_ok=ensemble_ok,
        )

        logger.info(
            "place_recommendation_status",
            extra={
                "status": tool_response.status.value,
                "source": tool_response.source.value,
                "candidate_count": candidate_count,
                "result_count": len(places),
                "top5_local_ratio": fairness_audit.top5_local_ratio,
                "missing_local_factor_count": fairness_audit.missing_local_factor_count,
                "warnings": fairness_audit.warnings,
            },
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
            fairness_audit=fairness_audit,
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
        fairness_audit: FairnessAudit | None = None,
    ) -> ChatResponse:
        source_value = source.value if source else "none"
        reasoning_log = (
            f"place_recommendation status={status.value} source={source_value} "
            f"candidate_count={candidate_count} result_count={len(places)}"
        )
        if fairness_audit is not None:
            reasoning_log += (
                f" top5_local_ratio={fairness_audit.top5_local_ratio}"
                f" missing_local_factor={fairness_audit.missing_local_factor_count}"
            )
            if fairness_audit.warnings:
                reasoning_log += f" warnings={','.join(fairness_audit.warnings)}"
        return ChatResponse(
            session_id=session_id,
            message=message,
            citations=[],
            places=places,
            reasoning_log=reasoning_log,
            intent=PLACE_RECOMMENDATION_INTENT,
            latency_ms=latency_ms,
            fallback=fallback,
            fairness_audit=fairness_audit,
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
        return f"Mình tìm được {result_count} địa điểm phù hợp quanh Hàm Ninh. Bạn có thể mở từng thẻ địa điểm để xem bản đồ, điểm đánh giá và lý do xếp hạng."
    if status == PlaceToolStatus.EMPTY:
        return "Mình chưa tìm thấy địa điểm phù hợp quanh Hàm Ninh cho yêu cầu này. Bạn thử nói rõ loại địa điểm, ngân sách hoặc khu vực gần đâu nhé."
    if status == PlaceToolStatus.CREDENTIALS_BLOCKED:
        return "Tính năng tìm địa điểm đang thiếu cấu hình Places API trên máy chủ, nên mình chưa thể trả kết quả địa điểm thật lúc này."
    if status == PlaceToolStatus.UPSTREAM_ERROR:
        return "Tính năng tìm địa điểm đang tạm lỗi từ Places API. Bạn thử lại sau một chút nhé."
    if status == PlaceToolStatus.INVALID_REQUEST:
        return "Mình chưa tìm được vì yêu cầu tìm địa điểm chưa đủ rõ. Bạn thử viết ngắn hơn, ví dụ: 'nhà hàng hải sản gần Hàm Ninh'."
    return "Tính năng tìm địa điểm đang tạm không khả dụng. Bạn thử lại sau nhé."


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


FAIRNESS_LOCAL_THRESHOLD = 0.6  # local_factor >= this counts as "local"
FAIRNESS_TOP_K = 5  # top-K window for local representation target
FAIRNESS_TOP5_TARGET_RATIO = 0.4  # target local fraction in top-K


def _is_local(result: PlaceResult) -> bool:
    """Return True when result carries a local_factor meeting the documented threshold."""
    return (result.local_factor or 0.0) >= FAIRNESS_LOCAL_THRESHOLD


def _balance_fairness(
    results: list[PlaceResult],
    *,
    target_ratio: float = FAIRNESS_TOP5_TARGET_RATIO,
    top_k: int = FAIRNESS_TOP_K,
) -> list[PlaceResult]:
    """Reorder results so top-K local representation meets the target ratio.

    Strategy: promote the highest-scoring local candidates from below the top-K
    window into positions just outside the non-local top-K candidates, preserving
    relative ordering as much as possible. Only candidates already in the list are
    promoted (no invented entries).

    Returns a reordered list with the same elements — only ordering changes.
    """
    if not results:
        return results

    top_k_window = results[:top_k]
    remaining = results[top_k:]

    # Separate top-K into local and non-local
    top_local = [r for r in top_k_window if _is_local(r)]
    top_non_local = [r for r in top_k_window if not _is_local(r)]

    # Locals below the top-K window that could be promoted
    below_local = [r for r in remaining if _is_local(r)]
    below_non_local = [r for r in remaining if not _is_local(r)]

    # Calculate how many locals we need in top-K
    needed_locals = max(0, int(top_k * target_ratio) - len(top_local))
    available_locals = len(below_local)

    if needed_locals == 0 or available_locals == 0:
        # Already compliant or no locals to promote — no reordering needed
        return results

    # Promote the first `needed_locals` locals from below the window
    promote_count = min(needed_locals, available_locals)
    to_promote = below_local[:promote_count]
    below_local = below_local[promote_count:]

    # Build new top-K: keep existing locals first, then add promoted locals,
    # then fill with non-locals that were displaced.
    displaced_non_local = top_non_local[len(top_local):len(top_local) + len(to_promote)]
    new_top_k = top_local + to_promote + [r for r in top_non_local if r not in displaced_non_local]

    # Ensure exactly top_k items in new_top_k
    new_top_k = new_top_k[:top_k]

    # Reassemble: new top-K + promoted-remaining locals + displaced non-locals + rest
    new_remaining = below_local + displaced_non_local + below_non_local

    return new_top_k + new_remaining


def _is_candidate_local(candidate: PlaceCandidate) -> bool:
    """Return True when candidate carries a local_factor meeting the threshold."""
    return (candidate.local_factor or 0.0) >= FAIRNESS_LOCAL_THRESHOLD


def _compute_fairness_audit(
    candidates: list[PlaceCandidate],
    results: list[PlaceResult],
    provider_status: PlaceToolStatus,
    route_enrichment_ok: bool = True,
    ensemble_ok: bool = True,
) -> FairnessAudit:
    """Compute a structured fairness audit snapshot from candidate/result data.

    Returns a FairnessAudit with safe, redacted diagnostics — no API keys,
    raw provider payloads, or user PII.
    """
    candidate_count = len(candidates)
    result_count = len(results)

    # Count candidates missing local_factor metadata
    missing_local_factor_count = sum(
        1 for c in candidates if c.local_factor is None
    )

    # Compute top-5 local ratio
    top_k = results[:FAIRNESS_TOP_K]
    if top_k:
        local_in_top5 = sum(
            1 for r in top_k if (r.local_factor or 0.0) >= FAIRNESS_LOCAL_THRESHOLD
        )
        top5_local_ratio = local_in_top5 / len(top_k)
    else:
        top5_local_ratio = 0.0

    # Build warning list
    warnings: list[str] = []
    if provider_status != PlaceToolStatus.OK:
        warnings.append(FairnessWarningType.PROVIDER_NON_OK.value)
    if not route_enrichment_ok:
        warnings.append(FairnessWarningType.ROUTE_ENRICHMENT_FALLBACK.value)
    if not ensemble_ok:
        warnings.append(FairnessWarningType.ENSEMBLE_FALLBACK.value)
    if missing_local_factor_count > 0:
        warnings.append(FairnessWarningType.MISSING_LOCAL_FACTOR_METADATA.value)

    # Check if supply limits fair representation
    local_candidates = sum(
        1 for c in candidates if (c.local_factor or 0.0) >= FAIRNESS_LOCAL_THRESHOLD
    )
    top5_target = max(1, int(FAIRNESS_TOP_K * 0.4))  # 40% of top-5 ≈ 2
    if local_candidates < top5_target and candidate_count >= FAIRNESS_TOP_K:
        warnings.append(FairnessWarningType.INSUFFICIENT_LOCAL_CANDIDATES.value)

    return FairnessAudit(
        candidate_count=candidate_count,
        result_count=result_count,
        top5_local_ratio=round(top5_local_ratio, 4),
        missing_local_factor_count=missing_local_factor_count,
        provider_status=provider_status.value,
        warnings=warnings,
    )
