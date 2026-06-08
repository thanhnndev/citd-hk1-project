"""Deterministic place recommendation seam grounded in Places tool output."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote

from pydantic import ValidationError

from app.models.places import (
    DEFAULT_SEARCH_RADIUS_METERS,
    HAM_NINH_CENTER,
    FairnessAudit,
    FairnessWarningType,
    PlaceAuditEvent,
    PlaceAuditPhase,
    PlaceCandidate,
    PlaceDecisionTrace,
    PlaceSearchRequest,
    PlaceToolResponse,
    PlaceToolSource,
    PlaceToolStatus,
)
from app.models.request import LatLng
from app.models.response import ChatResponse, PlaceExplanation, PlaceResult, ScoreBreakdown
from agents.ranking.fairness_reranker import FairnessReranker
from agents.ranking.feature_extractor import FeatureExtractor
from agents.tools.places_service import GooglePlacesService
from agents.tools.routes_service import GoongRoutesService

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = 10
PLACE_RECOMMENDATION_INTENT = "place_recommendation"


class PlaceDecisionTracer:
    """Bounded, redacted audit event builder for the search_places decision path.

    Collects PlaceAuditEvent instances across recommendation phases and produces
    a PlaceDecisionTrace at the end. O(1) per phase; no network calls.
    """

    def __init__(self, *, session_id: str, started: float) -> None:
        self._session_id = session_id
        self._started = started
        self._events: list[PlaceAuditEvent] = []
        self._credential_status: str | None = None
        self._provider_source: str | None = None

    # -- public API --

    def emit(
        self,
        event: str,
        phase: PlaceAuditPhase,
        *,
        detail: dict | None = None,
    ) -> None:
        """Record a single audit event with elapsed time since request start."""
        self._events.append(PlaceAuditEvent(
            event=event,
            phase=phase,
            detail=detail or {},
            elapsed_ms=_elapsed_ms(self._started),
        ))

    def set_credential_status(self, status: str) -> None:
        """Set the final credential status label."""
        self._credential_status = status

    def set_provider_source(self, source: str) -> None:
        """Set the final provider/source label."""
        self._provider_source = source

    def build(self) -> PlaceDecisionTrace:
        """Produce the immutable decision trace with all collected events."""
        trace = PlaceDecisionTrace(
            events=list(self._events),
            session_id=self._session_id,
            credential_status=self._credential_status,
            provider_source=self._provider_source,
        )
        return trace


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

    async def recommend(
        self,
        *,
        query: str,
        language: str = "vi",
        session_id: str,
        budget: str | None = None,
        accessibility: bool | None = None,
        user_location: dict[str, float] | None = None,
    ) -> ChatResponse:
        started = time.perf_counter()
        tracer = PlaceDecisionTracer(session_id=session_id, started=started)

        # Track which preferences were actually applied (for diagnostics)
        preference_budget_applied = False
        preference_accessibility_applied = accessibility is True
        user_location_applied = False

        try:
            request, budget_was_valid, user_loc_was_valid = self._build_request(
                query=query,
                language=language,
                budget=budget,
                accessibility=accessibility,
                user_location=user_location,
            )
            preference_budget_applied = budget_was_valid
            user_location_applied = user_loc_was_valid
            tracer.emit("request_built", PlaceAuditPhase.REQUEST, detail={
                "language_code": request.language_code,
                "budget_valid": budget_was_valid,
                "user_location_valid": user_loc_was_valid,
                "max_result_count": request.max_result_count,
            })
        except ValidationError:
            tracer.emit("invalid_request", PlaceAuditPhase.REQUEST, detail={
                "query_length": len(query) if query else 0,
            })
            tracer.set_credential_status("unknown")
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
                decision_trace=tracer.build(),
            )

        try:
            tool_response = await self._places_tool.text_search(request)
        except Exception as exc:  # noqa: BLE001 - service boundary must fail closed and sanitize.
            logger.warning("place_recommendation_tool_error", extra={"error_type": type(exc).__name__})
            tracer.emit("provider_error", PlaceAuditPhase.PROVIDER, detail={
                "error_type": type(exc).__name__,
            })
            tracer.set_credential_status("unavailable")
            tracer.set_provider_source("none")
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
                decision_trace=tracer.build(),
            )

        candidate_count = len(tool_response.candidates)
        if tool_response.status != PlaceToolStatus.OK:
            # Provider returned non-OK status — record credential/status info
            if tool_response.status == PlaceToolStatus.CREDENTIALS_BLOCKED:
                tracer.emit("provider_credentials_blocked", PlaceAuditPhase.CREDENTIAL, detail={
                    "source": tool_response.source.value,
                })
                tracer.set_credential_status("blocked")
            elif tool_response.status == PlaceToolStatus.UNAVAILABLE:
                tracer.emit("provider_unavailable", PlaceAuditPhase.CREDENTIAL, detail={
                    "source": tool_response.source.value,
                })
                tracer.set_credential_status("unavailable")
            elif tool_response.status == PlaceToolStatus.UPSTREAM_ERROR:
                tracer.emit("provider_error", PlaceAuditPhase.PROVIDER, detail={
                    "status": tool_response.status.value,
                })
                tracer.set_credential_status("unavailable")
            else:
                tracer.emit("provider_ok", PlaceAuditPhase.PROVIDER, detail={
                    "status": tool_response.status.value,
                    "candidate_count": candidate_count,
                })
                tracer.set_credential_status("live")

            tracer.set_provider_source(tool_response.source.value)
            logger.info(
                "place_recommendation_status",
                extra={
                    "status": tool_response.status.value,
                    "source": tool_response.source.value,
                    "candidate_count": candidate_count,
                    "result_count": 0,
                    "preference_budget_applied": preference_budget_applied,
                    "preference_accessibility_applied": preference_accessibility_applied,
                    "user_location_applied": user_location_applied,
                },
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
                preference_flags=_preference_flags(
                    budget_applied=preference_budget_applied,
                    accessibility_applied=preference_accessibility_applied,
                    user_location_applied=user_location_applied,
                ),
                decision_trace=tracer.build(),
            )

        # Provider returned OK — record provider event
        tracer.emit("provider_called", PlaceAuditPhase.PROVIDER, detail={
            "status": tool_response.status.value,
            "source": tool_response.source.value,
            "candidate_count": candidate_count,
        })
        tracer.set_provider_source(tool_response.source.value)
        if tool_response.source == PlaceToolSource.CACHE:
            tracer.emit("cache_hit", PlaceAuditPhase.CACHE, detail={
                "candidate_count": candidate_count,
            })
            tracer.set_credential_status("live")
        else:
            tracer.set_credential_status("live")

        # Route enrichment (optional — degrades gracefully)
        candidates = tool_response.candidates
        route_enrichment_ok = True
        try:
            if self._routes_service is not None:
                candidates = await self._routes_service.enrich_candidates(
                    tool_response.candidates, origin=request.effective_origin
                )
                tracer.emit("route_enrichment_ok", PlaceAuditPhase.ROUTE, detail={
                    "candidate_count": len(candidates),
                })
        except Exception as exc:  # noqa: BLE001
            logger.warning("route_enrichment_failed", extra={"error_type": type(exc).__name__})
            candidates = tool_response.candidates
            route_enrichment_ok = False
            tracer.emit("route_enrichment_fallback", PlaceAuditPhase.ROUTE, detail={
                "error_type": type(exc).__name__,
            })

        # Preference-aware and product-intent filtering/reranking.
        # This is not intent routing: the LLM already chose search_places.
        # Here we protect end-user quality by suppressing provider candidates
        # that are places data but not useful travel recommendations.
        pre_filter_count = len(candidates)
        candidates, filtered_count = _apply_preference_filters(candidates, request)
        frame = _build_recommendation_frame(request.query)
        candidates, product_filtered_count = _apply_product_quality_filters(candidates, frame)
        filtered_count += product_filtered_count

        if filtered_count > 0 or preference_budget_applied or preference_accessibility_applied:
            tracer.emit("preference_filter_applied", PlaceAuditPhase.FILTER, detail={
                "pre_filter_count": pre_filter_count,
                "post_filter_count": len(candidates),
                "filtered_count": filtered_count,
                "budget_applied": preference_budget_applied,
                "accessibility_applied": preference_accessibility_applied,
                "product_filtered_count": product_filtered_count,
            })
        else:
            tracer.emit("preference_filter_skipped", PlaceAuditPhase.FILTER)

        ensemble_ok = True
        provider_source_val = tool_response.source.value
        provider_status_val = tool_response.status.value
        try:
            places = _reranked_results(
                candidates, request.query,
                provider_source=provider_source_val,
                provider_status=provider_status_val,
                request=request,
                language=language,
            )
            tracer.emit("reranking_ensemble", PlaceAuditPhase.RERANK, detail={
                "candidate_count": len(candidates),
                "result_count": len(places),
            })
        except Exception as exc:  # noqa: BLE001 - ensemble pipeline fails closed.
            logger.warning("ensemble_reranking_failed", extra={"error_type": type(exc).__name__})
            places = _grounded_results(
                candidates,
                provider_source=provider_source_val,
                provider_status=provider_status_val,
                request=request,
                language=language,
            )
            ensemble_ok = False
            tracer.emit("reranking_fallback", PlaceAuditPhase.RERANK, detail={
                "error_type": type(exc).__name__,
                "candidate_count": len(candidates),
            })

        # Fairness balancing: reorder results so top-K local representation
        # meets the 40% target when enough local candidates exist.
        places = _balance_fairness(places)
        if places:
            tracer.emit("fairness_balanced", PlaceAuditPhase.FAIRNESS, detail={
                "result_count": len(places),
            })

        fairness_audit = _compute_fairness_audit(
            candidates=candidates,
            results=places,
            provider_status=tool_response.status,
            route_enrichment_ok=route_enrichment_ok,
            ensemble_ok=ensemble_ok,
        )

        # Composition: deterministic result assembly
        tracer.emit("composition_deterministic", PlaceAuditPhase.COMPOSE, detail={
            "result_count": len(places),
            "candidate_count": len(candidates),
        })

        logger.info(
            "place_recommendation_status",
            extra={
                "status": tool_response.status.value,
                "source": tool_response.source.value,
                "candidate_count": pre_filter_count,
                "result_count": len(places),
                "filtered_count": filtered_count,
                "preference_budget_applied": preference_budget_applied,
                "preference_accessibility_applied": preference_accessibility_applied,
                "user_location_applied": user_location_applied,
                "top5_local_ratio": fairness_audit.top5_local_ratio,
                "missing_geo_locality_count": fairness_audit.missing_geo_locality_count,
                "warnings": fairness_audit.warnings,
            },
        )
        return self._chat_response(
            session_id=session_id,
            message=_message_for_status(
                tool_response.status,
                result_count=len(places),
                is_commercial=_is_commercial_query(candidates),
                language_code=request.language_code,
                display_names=[place.display_name for place in places],
                frame=frame,
            ),
            status=tool_response.status,
            source=tool_response.source,
            candidate_count=candidate_count,
            places=places,
            latency_ms=_elapsed_ms(started),
            fallback=False,
            fairness_audit=fairness_audit,
            preference_flags=_preference_flags(
                budget_applied=preference_budget_applied,
                accessibility_applied=preference_accessibility_applied,
                user_location_applied=user_location_applied,
                filtered_count=filtered_count,
            ),
            decision_trace=tracer.build(),
        )

    def _build_request(
        self,
        *,
        query: str,
        language: str,
        budget: str | None = None,
        accessibility: bool | None = None,
        user_location: dict[str, float] | None = None,
    ) -> PlaceSearchRequest:
        language_code = language if language in {"vi", "en"} else "vi"

        # Map budget to PriceLevel enum — only if label is valid
        budget_filter = None
        budget_was_valid = False
        if budget:
            from app.models.places import PriceLevel
            budget_map = {
                "free": PriceLevel.FREE,
                "inexpensive": PriceLevel.INEXPENSIVE,
                "moderate": PriceLevel.MODERATE,
                "expensive": PriceLevel.EXPENSIVE,
                "very_expensive": PriceLevel.VERY_EXPENSIVE,
            }
            if budget in budget_map:
                budget_filter = [budget_map[budget]]
                budget_was_valid = True

        # Build user_location LatLng if provided — validate coordinate ranges
        user_loc = None
        user_loc_was_valid = False
        if user_location:
            try:
                lat = user_location.get("lat")
                lng = user_location.get("lng")
                if lat is not None and lng is not None:
                    lat_f = float(lat)
                    lng_f = float(lng)
                    # Coordinate range validation: lat in [-90, 90], lng in [-180, 180]
                    if -90 <= lat_f <= 90 and -180 <= lng_f <= 180:
                        user_loc = LatLng(lat=lat_f, lng=lng_f)
                        user_loc_was_valid = True
            except (TypeError, ValueError, AttributeError):
                user_loc = None

        return PlaceSearchRequest(
            query=query,
            language_code=language_code,
            location_bias=HAM_NINH_CENTER.model_copy(),
            radius_meters=DEFAULT_SEARCH_RADIUS_METERS,
            max_result_count=self._max_result_count,
            budget_filter=budget_filter,
            wheelchair_accessible_preference=accessibility,
            user_location=user_loc,
        ), budget_was_valid, user_loc_was_valid

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
        preference_flags: str | None = None,
        decision_trace: PlaceDecisionTrace | None = None,
    ) -> ChatResponse:
        source_value = source.value if source else "none"
        reasoning_log = (
            f"place_recommendation status={status.value} source={source_value} "
            f"candidate_count={candidate_count} result_count={len(places)}"
        )
        if preference_flags:
            reasoning_log += f" {preference_flags}"
        if fairness_audit is not None:
            reasoning_log += (
                f" top5_local_ratio={fairness_audit.top5_local_ratio}"
                f" missing_geo_locality={fairness_audit.missing_geo_locality_count}"
            )
            if fairness_audit.warnings:
                reasoning_log += f" warnings={','.join(fairness_audit.warnings)}"
        if decision_trace is not None:
            reasoning_log += (
                f" audit_events={decision_trace.total_events}"
                f" credential_status={decision_trace.credential_status}"
            )
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
            decision_trace=decision_trace,
        )


def _reranked_results(
    candidates: list[PlaceCandidate], query: str,
    *,
    provider_source: str | None = None,
    provider_status: str | None = None,
    request: PlaceSearchRequest | None = None,
    language: str = "vi",
) -> list[PlaceResult]:
    """Run candidates through FeatureExtractor → FairnessReranker pipeline."""
    extractor = FeatureExtractor()
    feature_dicts = [
        extractor.extract(candidate, query, user_location=None)
        for candidate in candidates
    ]

    sorted_candidates, score_breakdowns = FairnessReranker().rerank(
        candidates, feature_dicts
    )

    # Derive preference match signals from the request
    numeric_levels = request.numeric_price_levels if request else None
    accessibility_pref = request.wheelchair_accessible_preference if request else None

    results: list[PlaceResult] = []
    for candidate, breakdown in zip(sorted_candidates, score_breakdowns):
        accessibility_score = candidate.accessibility_score
        if accessibility_score is None and candidate.accessibility_options:
            accessibility_score = (
                1.0 if any(candidate.accessibility_options.values()) else 0.0
            )

        # Budget match: candidate price_level within requested budget range
        budget_matched = False
        if numeric_levels is not None and candidate.price_level is not None:
            budget_matched = candidate.price_level in set(numeric_levels)

        # Accessibility match: candidate has positive options AND user requested it
        accessibility_matched = (
            accessibility_pref is True
            and bool(candidate.accessibility_options)
            and any(candidate.accessibility_options.values())
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
                primary_type_display_name=candidate.primary_type_display_name,
                rating=candidate.rating,
                user_rating_count=candidate.user_rating_count,
                price_level=candidate.price_level,
                open_now=candidate.open_now,
                business_status=candidate.business_status,
                current_opening_hours=candidate.current_opening_hours,
                regular_opening_hours=candidate.regular_opening_hours,
                payment_options=candidate.payment_options,
                parking_options=candidate.parking_options,
                editorial_summary=candidate.editorial_summary,
                generative_summary=candidate.generative_summary,
                review_summary=candidate.review_summary,
                reviews=candidate.reviews,
                photos=candidate.photos,
                service_options=_service_options(candidate),
                geo_locality=candidate.geo_locality,
                final_score=breakdown.final_score,
                score_breakdown=breakdown,
                accessibility_score=accessibility_score,
                accessibility_warning=candidate.accessibility_warning,
                map_uri=candidate.map_uri
                or _maps_url(candidate.place_id),
                explanation=_build_place_explanation(
                    candidate=candidate,
                    breakdown=breakdown,
                    accessibility_score=accessibility_score,
                    provider_source=provider_source,
                    provider_status=provider_status,
                    budget_matched=budget_matched,
                    accessibility_matched=accessibility_matched,
                    language=language,
                    frame=_build_recommendation_frame(query),
                ),
            )
        )

    return results


def _grounded_results(
    candidates: list[PlaceCandidate],
    *,
    provider_source: str | None = None,
    provider_status: str | None = None,
    request: PlaceSearchRequest | None = None,
    language: str = "vi",
) -> list[PlaceResult]:
    """Fallback path: return candidates with default ensemble ScoreBreakdown."""
    numeric_levels = request.numeric_price_levels if request else None
    accessibility_pref = request.wheelchair_accessible_preference if request else None

    results: list[PlaceResult] = []
    for i, candidate in enumerate(candidates):
        accessibility_score = candidate.accessibility_score
        if accessibility_score is None and candidate.accessibility_options:
            accessibility_score = (
                1.0 if any(candidate.accessibility_options.values()) else 0.0
            )

        # Budget match: candidate price_level within requested budget range
        budget_matched = False
        if numeric_levels is not None and candidate.price_level is not None:
            budget_matched = candidate.price_level in set(numeric_levels)

        # Accessibility match: candidate has positive options AND user requested it
        accessibility_matched = (
            accessibility_pref is True
            and bool(candidate.accessibility_options)
            and any(candidate.accessibility_options.values())
        )

        breakdown = ScoreBreakdown(
            tree1_locality=0.5,
            tree2_proximity=0.5,
            tree3_quality=0.5,
            s_bag=0.5,
            delta1_fairness=0.0,
            delta2_access=0.0,
            final_score=0.5,
            rank=i + 1,
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
                primary_type_display_name=candidate.primary_type_display_name,
                rating=candidate.rating,
                user_rating_count=candidate.user_rating_count,
                price_level=candidate.price_level,
                open_now=candidate.open_now,
                business_status=candidate.business_status,
                current_opening_hours=candidate.current_opening_hours,
                regular_opening_hours=candidate.regular_opening_hours,
                payment_options=candidate.payment_options,
                parking_options=candidate.parking_options,
                editorial_summary=candidate.editorial_summary,
                generative_summary=candidate.generative_summary,
                review_summary=candidate.review_summary,
                reviews=candidate.reviews,
                photos=candidate.photos,
                service_options=_service_options(candidate),
                geo_locality=candidate.geo_locality,
                final_score=0.5,
                score_breakdown=breakdown,
                accessibility_score=accessibility_score,
                accessibility_warning=candidate.accessibility_warning,
                map_uri=candidate.map_uri
                or _maps_url(candidate.place_id),
                explanation=_build_place_explanation(
                    candidate=candidate,
                    breakdown=breakdown,
                    accessibility_score=accessibility_score,
                    fallback=True,
                    provider_source=provider_source,
                    provider_status=provider_status,
                    budget_matched=budget_matched,
                    accessibility_matched=accessibility_matched,
                    language=language,
                    frame=_build_recommendation_frame(request.query) if request else None,
                ),
            )
        )

    return results


def _make_place_specific_reason(
    *,
    candidate: PlaceCandidate,
    detail_highlights: list[str],
    fallback: bool,
    language: str,
    frame: RecommendationFrame | None = None,
) -> str:
    type_label = candidate.primary_type_display_name or (candidate.primary_type or "place").replace("_", " ")
    rating_bits: list[str] = []
    if candidate.rating is not None:
        if language == "vi":
            if candidate.rating >= 4.3:
                rating_bits.append(f"điểm mạnh {candidate.rating:.1f}⭐")
            elif candidate.rating >= 4.0:
                rating_bits.append(f"đánh giá khá {candidate.rating:.1f}⭐")
            else:
                rating_bits.append(f"đánh giá trung bình {candidate.rating:.1f}⭐")
        else:
            if candidate.rating >= 4.3:
                rating_bits.append(f"strong rating {candidate.rating:.1f}⭐")
            elif candidate.rating >= 4.0:
                rating_bits.append(f"solid rating {candidate.rating:.1f}⭐")
            else:
                rating_bits.append(f"mixed rating {candidate.rating:.1f}⭐")
    if candidate.user_rating_count:
        rating_bits.append(f"{candidate.user_rating_count} reviews" if language != "vi" else f"{candidate.user_rating_count} lượt đánh giá")
    status_bits: list[str] = []
    if candidate.open_now is True:
        status_bits.append("đang mở cửa" if language == "vi" else "open now")
    if candidate.price_level is not None:
        status_bits.append(("mức giá" if language == "vi" else "price level") + f" {candidate.price_level}")

    if frame is not None:
        suitability = _evaluate_candidate_suitability(candidate, frame)
        return suitability.primary_reason_vi if language == "vi" else suitability.primary_reason_en

    if detail_highlights:
        lead = detail_highlights[0].rstrip(".")
        if language == "vi":
            return f"{candidate.display_name} có thông tin mô tả phù hợp với yêu cầu: {lead}."
        return f"{candidate.display_name} has details that match the request: {lead}."

    joined_rating = ", ".join(rating_bits)
    joined_status = ", ".join(status_bits)
    if language == "vi":
        pieces = [f"{candidate.display_name} là {type_label}"]
        if joined_rating:
            pieces.append(f"có tín hiệu đánh giá từ {joined_rating}")
        if joined_status:
            pieces.append(joined_status)
        if fallback:
            pieces.append("fallback: được giữ lại từ dữ liệu dự phòng")
        return "; ".join(pieces) + "."

    pieces = [f"{candidate.display_name} is a {type_label}"]
    if joined_rating:
        pieces.append(f"quality signal: {joined_rating}")
    if joined_status:
        pieces.append(joined_status)
    if fallback:
        pieces.append("kept from fallback place data")
    return "; ".join(pieces) + "."

def _norm_query(text: str) -> str:
    return " ".join((text or "").strip().lower().split())

@dataclass(frozen=True)
class RecommendationFrame:
    """Product-level interpretation of a place request.

    This is intentionally broader than one query case. The LLM has already
    selected the places tool; this frame describes what a useful end-user
    recommendation must optimize for.
    """

    goal: str = "visit"
    audience: str = "general"
    desired_roles: frozenset[str] = field(default_factory=lambda: frozenset({"visit", "eat", "stay"}))
    disallowed_roles: frozenset[str] = field(default_factory=lambda: frozenset({"service", "shop"}))
    constraints: frozenset[str] = field(default_factory=frozenset)

@dataclass(frozen=True)
class CandidateSuitability:
    role: str
    score: float
    primary_reason_vi: str
    primary_reason_en: str
    disqualified: bool = False
    caveats_vi: tuple[str, ...] = ()
    caveats_en: tuple[str, ...] = ()

_VISIT_TYPES = frozenset({"tourist_attraction", "amusement_park", "museum", "park", "zoo", "aquarium", "waterfall"})
_EAT_TYPES = frozenset({"restaurant", "seafood_restaurant", "vietnamese_restaurant", "food", "cafe", "coffee_shop"})
_STAY_TYPES = frozenset({"lodging", "hotel", "resort", "guest_house", "bed_and_breakfast", "homestay"})
_SHOP_TYPES = frozenset({"store", "shopping_mall", "clothing_store", "supermarket", "pharmacy"})
_SERVICE_TYPES = frozenset({"child_care_agency", "day_care_center", "preschool", "school", "doctor", "hospital", "local_government_office", "real_estate_agency", "bank", "atm"})

_GOAL_TERMS = {
    "itinerary": ("lịch trình", "lich trinh", "ghé đâu", "ghe dau", "đi đâu", "di dau", "visit", "where should", "plan"),
    "food": ("ăn", "an ", "quán", "quan", "nhà hàng", "nha hang", "hải sản", "hai san", "food", "restaurant", "seafood"),
    "stay": ("homestay", "khách sạn", "khach san", "hotel", "stay", "lodging"),
}
_AUDIENCE_TERMS = {
    "family": ("trẻ em", "tre em", "trẻ nhỏ", "tre nho", "em bé", "em be", "bé ", "be ", "gia đình", "gia dinh", "con nhỏ", "con nho", "kids", "children", "child", "family"),
    "accessibility": ("xe lăn", "xe lan", "wheelchair", "accessible", "tiếp cận", "tiep can", "người già", "nguoi gia", "elderly"),
}

def _build_recommendation_frame(query: str) -> RecommendationFrame:
    text = _norm_query(query)
    goal = "visit"
    if any(term in text for term in _GOAL_TERMS["food"]):
        goal = "food"
    if any(term in text for term in _GOAL_TERMS["stay"]):
        goal = "stay"
    if any(term in text for term in _GOAL_TERMS["itinerary"]):
        goal = "itinerary"

    audience = "general"
    if any(term in text for term in _AUDIENCE_TERMS["family"]):
        audience = "family"
    elif any(term in text for term in _AUDIENCE_TERMS["accessibility"]):
        audience = "accessibility"

    desired_by_goal = {
        "food": frozenset({"eat"}),
        "stay": frozenset({"stay"}),
        "itinerary": frozenset({"visit", "eat", "rest"}),
        "visit": frozenset({"visit", "eat", "stay"}),
    }
    constraints: set[str] = set()
    if audience == "family":
        constraints.add("low_friction")
    if audience == "accessibility":
        constraints.add("accessibility")
    return RecommendationFrame(
        goal=goal,
        audience=audience,
        desired_roles=desired_by_goal.get(goal, frozenset({"visit", "eat", "stay"})),
        constraints=frozenset(constraints),
    )

def _candidate_type_set(candidate: PlaceCandidate) -> set[str]:
    return {str(t).lower() for t in ([candidate.primary_type] + list(candidate.types or [])) if t}

def _candidate_role(candidate: PlaceCandidate) -> str:
    types = _candidate_type_set(candidate)
    if types & _SERVICE_TYPES:
        return "service"
    if types & _SHOP_TYPES:
        return "shop"
    if types & _EAT_TYPES:
        return "eat"
    if types & _STAY_TYPES:
        return "stay"
    if types & _VISIT_TYPES:
        return "visit"
    return "unknown"

def _evaluate_candidate_suitability(candidate: PlaceCandidate, frame: RecommendationFrame) -> CandidateSuitability:
    role = _candidate_role(candidate)
    disqualified = role in frame.disallowed_roles or (role not in frame.desired_roles and frame.goal in {"food", "stay", "itinerary"})
    score = 0.0
    if role in frame.desired_roles:
        score += 4.0
    if role == "unknown":
        score -= 1.0
    if disqualified:
        score -= 10.0
    if candidate.rating is not None:
        score += min(candidate.rating, 5.0) / 5.0
    if candidate.user_rating_count:
        score += min(candidate.user_rating_count, 1000) / 1500.0
    if candidate.open_now is True:
        score += 0.2
    if "accessibility" in frame.constraints and candidate.accessibility_options and any(candidate.accessibility_options.values()):
        score += 1.0
    if "low_friction" in frame.constraints and candidate.route_context and candidate.route_context.duration_seconds is not None:
        score -= min(candidate.route_context.duration_seconds / 5400.0, 1.0)

    role_vi = {"visit": "điểm tham quan", "eat": "điểm ăn uống", "stay": "nơi lưu trú", "shop": "cửa hàng", "service": "dịch vụ", "unknown": "địa điểm"}.get(role, "địa điểm")
    role_en = {"visit": "visit stop", "eat": "food stop", "stay": "place to stay", "shop": "shop", "service": "service", "unknown": "place"}.get(role, "place")
    if disqualified:
        return CandidateSuitability(
            role=role,
            score=score,
            primary_reason_vi=f"{candidate.display_name} giống {role_vi} hơn là gợi ý phù hợp trực tiếp cho yêu cầu này.",
            primary_reason_en=f"{candidate.display_name} looks more like a {role_en} than a direct fit for this request.",
            disqualified=True,
        )
    reason_vi = f"{candidate.display_name} phù hợp như một {role_vi} cho mục tiêu chuyến đi."
    reason_en = f"{candidate.display_name} fits as a {role_en} for this travel goal."
    if frame.audience == "family":
        reason_vi = f"{candidate.display_name} đáng cân nhắc cho nhóm đi cùng trẻ em vì vai trò chính là {role_vi}, không phải dịch vụ/cửa hàng ngoài mục đích tham quan."
        reason_en = f"{candidate.display_name} is worth considering for a group with children because it functions as a {role_en}, not an unrelated shop or service."
    return CandidateSuitability(role=role, score=score, primary_reason_vi=reason_vi, primary_reason_en=reason_en)

def _apply_product_quality_filters(candidates: list[PlaceCandidate], frame: RecommendationFrame) -> tuple[list[PlaceCandidate], int]:
    if not candidates:
        return candidates, 0
    evaluated = [(candidate, _evaluate_candidate_suitability(candidate, frame)) for candidate in candidates]
    kept = [(candidate, suitability) for candidate, suitability in evaluated if not suitability.disqualified]
    kept.sort(key=lambda item: item[1].score, reverse=True)
    return [candidate for candidate, _ in kept], len(evaluated) - len(kept)

def _service_options(candidate: PlaceCandidate) -> dict[str, bool | None]:
    return {
        "takeout": candidate.takeout,
        "delivery": candidate.delivery,
        "dine_in": candidate.dine_in,
        "reservable": candidate.reservable,
        "serves_breakfast": candidate.serves_breakfast,
        "serves_lunch": candidate.serves_lunch,
        "serves_dinner": candidate.serves_dinner,
        "serves_beer": candidate.serves_beer,
        "serves_wine": candidate.serves_wine,
        "serves_vegetarian_food": candidate.serves_vegetarian_food,
    }

def _detail_highlights(candidate: PlaceCandidate) -> list[str]:
    highlights: list[str] = []
    if candidate.editorial_summary:
        highlights.append(candidate.editorial_summary[:180])
    elif candidate.generative_summary:
        highlights.append(candidate.generative_summary[:180])
    elif candidate.review_summary:
        highlights.append(candidate.review_summary[:180])
    service_labels = {
        "takeout": "takeout",
        "delivery": "delivery",
        "dine_in": "dine-in",
        "reservable": "reservations",
        "serves_vegetarian_food": "vegetarian options",
    }
    for key, label in service_labels.items():
        if getattr(candidate, key) is True:
            highlights.append(label)
    if candidate.payment_options:
        payments = ", ".join(k for k, v in candidate.payment_options.items() if v)
        if payments:
            highlights.append(f"payments: {payments}")
    if candidate.parking_options:
        parking = ", ".join(k for k, v in candidate.parking_options.items() if v)
        if parking:
            highlights.append(f"parking: {parking}")
    return highlights[:8]

def _redact_text(value: str, *, max_length: int = 240) -> str:
    """Strip API-key-like tokens, phone numbers, and truncate to bounded length.

    Order matters: API-key patterns are stripped first to avoid phone regex
    consuming digits within key tokens.

    API-key pattern: sk-, gsk-, AIza- prefixes followed by 8+ alphanumeric/dash chars.
    Secret pattern: key=, token=, secret= followed by non-whitespace.
    Phone pattern: + or digit start, 7+ digits with optional dashes/spaces, digit end.
    """
    import re
    # API-key-like tokens FIRST (before phone regex can consume their digits)
    value = re.sub(r"(?:sk|gsk|AIza)[\w\-]{8,}", "[key_redacted]", value, flags=re.IGNORECASE)
    value = re.sub(r"(?:key|token|secret)\s*=\s*\S+", "[secret_redacted]", value, flags=re.IGNORECASE)
    # Phone-like patterns (7+ consecutive digits with optional formatting)
    value = re.sub(r"\+?[\d][\d\s\-]{6,}\d", "[phone_redacted]", value)
    return value[:max_length]


def _make_friendly_reason(matched: list[str], fallback: bool, language: str) -> str:
    # Extract type, rating, open status, budget, accessibility
    place_type = None
    rating_ok = False
    open_now = False
    budget_ok = False
    access_ok = False

    for m in matched:
        if m.startswith("type:"):
            place_type = m.split(":", 1)[1]
        elif m == "provider_rating_available":
            rating_ok = True
        elif m == "open_now":
            open_now = True
        elif m == "budget_preference_matched":
            budget_ok = True
        elif m == "accessibility_preference_matched":
            access_ok = True

    if language == "vi":
        type_map = {
            "coffee_shop": "quán cà phê",
            "cafe": "quán cà phê",
            "restaurant": "nhà hàng",
            "tourist_attraction": "điểm tham quan",
            "lodging": "khách sạn/nơi lưu trú",
            "hotel": "khách sạn",
            "bar": "quán bar/bistro",
            "food": "địa điểm ăn uống",
            "park": "công viên",
            "museum": "bảo tàng",
        }
        type_str = type_map.get(place_type, "địa điểm") if place_type else "địa điểm"
        
        parts = []
        if budget_ok:
            parts.append("phù hợp ngân sách")
        if rating_ok:
            parts.append("có dữ liệu đánh giá từ nhà cung cấp")
        if open_now:
            parts.append("đang mở cửa")
        if access_ok:
            parts.append("hỗ trợ lối xe lăn")
            
        if not parts:
            if fallback:
                return f"Gợi ý {type_str} phù hợp dựa trên các tiêu chí tìm kiếm cơ bản (fallback, recommended)."
            return f"Gợi ý {type_str} chất lượng được đề xuất dựa trên các tiêu chí tối ưu (recommended)."
            
        # Join parts naturally
        if len(parts) == 1:
            desc = parts[0]
        elif len(parts) == 2:
            desc = f"{parts[0]} và {parts[1]}"
        else:
            desc = ", ".join(parts[:-1]) + f" và {parts[-1]}"
            
        capitalized_type = type_str.capitalize()
        if fallback:
            return f"{capitalized_type} được gợi ý dựa trên tiêu chí cơ bản vì {desc} (fallback, recommended)."
        return f"{capitalized_type} được gợi ý vì {desc} (recommended)."
    else:
        type_str = place_type.replace("_", " ") if place_type else "place"
        parts = []
        if budget_ok:
            parts.append("fits your budget")
        if rating_ok:
            parts.append("has provider rating data")
        if open_now:
            parts.append("is open now")
        if access_ok:
            parts.append("offers wheelchair access")
            
        if not parts:
            if fallback:
                return f"Recommended using fallback grounded place fields (fallback)."
            return f"Recommended by reranking grounded place fields (recommended)."
            
        if len(parts) == 1:
            desc = parts[0]
        elif len(parts) == 2:
            desc = f"{parts[0]} and {parts[1]}"
        else:
            desc = ", ".join(parts[:-1]) + f", and {parts[-1]}"
            
        if fallback:
            return f"Recommended using fallback grounded place fields because it {desc} (fallback)."
        return f"Recommended by reranking grounded place fields. It {desc} (recommended)."


def _build_place_explanation(
    *,
    candidate: PlaceCandidate,
    breakdown: ScoreBreakdown,
    accessibility_score: float | None,
    fallback: bool = False,
    provider_source: str | None = None,
    provider_status: str | None = None,
    budget_matched: bool = False,
    accessibility_matched: bool = False,
    language: str = "vi",
    frame: RecommendationFrame | None = None,
) -> PlaceExplanation:
    """Create a redacted explanation from normalized candidate fields only.

    Security: no raw provider JSON, no API keys, no phone numbers, no exact GPS.
    All text fields pass through _redact_text for PII/secret sanitization.
    """
    evidence: list[str] = ["place_id", "display_name", "score_breakdown"]
    matched: list[str] = []

    if candidate.primary_type:
        matched.append(f"type:{_redact_text(candidate.primary_type, max_length=40)}")
        evidence.append("primary_type")
    if candidate.primary_type_display_name:
        matched.append(f"type_label:{_redact_text(candidate.primary_type_display_name, max_length=40)}")
        evidence.append("primary_type_display_name")
    elif candidate.types:
        matched.append(f"type:{_redact_text(candidate.types[0], max_length=40)}")
        evidence.append("types")

    if candidate.price_level is not None:
        matched.append(f"price_level:{candidate.price_level}")
        evidence.append("price_level")
    detail_highlights = _detail_highlights(candidate)
    if detail_highlights:
        evidence.append("place_details")
    if candidate.rating is not None:
        matched.append("provider_rating_available")
        evidence.append("rating")
    if candidate.open_now is not None:
        matched.append("open_now" if candidate.open_now else "opening_status_known")
        evidence.append("open_now")

    # Preference matching signals (from request-level preferences)
    if budget_matched:
        matched.append("budget_preference_matched")
        evidence.append("budget_filter")
    if accessibility_matched:
        matched.append("accessibility_preference_matched")
        evidence.append("accessibility_options")

    geo_locality = candidate.geo_locality
    if geo_locality is None:
        local_context = "local signal unknown"
        fairness_note = "geo_locality missing; fairness treatment is conservative"
    elif geo_locality >= FAIRNESS_LOCAL_THRESHOLD:
        local_context = "strong local signal from normalized provider metadata"
        fairness_note = "supports local representation balancing"
        evidence.append("geo_locality")
    else:
        local_context = "limited local signal from normalized provider metadata"
        fairness_note = "included without overstating local ownership"
        evidence.append("geo_locality")

    if accessibility_score is None and not candidate.accessibility_warning and not candidate.accessibility_options:
        accessibility_note = "accessibility metadata unknown"
    elif candidate.accessibility_warning:
        accessibility_note = _redact_text(candidate.accessibility_warning)
        evidence.append("accessibility_warning")
    elif accessibility_score is not None:
        accessibility_note = f"accessibility score {accessibility_score:.2f}"
        evidence.append("accessibility_score")
    else:
        accessibility_note = "accessibility options available"
        evidence.append("accessibility_options")

    route_summary = "route metadata unavailable"
    if candidate.route_context is not None:
        evidence.append("route_context")
        parts: list[str] = []
        if candidate.route_context.travel_mode:
            parts.append(candidate.route_context.travel_mode)
        if candidate.route_context.distance_meters is not None:
            parts.append(f"{candidate.route_context.distance_meters}m")
        if candidate.route_context.duration_seconds is not None:
            parts.append(f"{round(candidate.route_context.duration_seconds / 60)}min")
        route_summary = "route " + ", ".join(parts) if parts else "route metadata limited"

    suitability = _evaluate_candidate_suitability(candidate, frame) if frame is not None else None
    primary_reason = _make_place_specific_reason(
        candidate=candidate,
        detail_highlights=detail_highlights,
        fallback=fallback,
        language=language,
        frame=frame,
    )
    primary_reason = _redact_text(primary_reason)

    score_factors: dict[str, float | int | str | None] = {
        "rank": breakdown.rank,
        "final_score": round(breakdown.final_score, 4),
        "geo_locality": round(geo_locality, 4) if geo_locality is not None else None,
        "rating": candidate.rating,
        "price_level": candidate.price_level,
        "recommendation_role": suitability.role if suitability else None,
        "suitability_score": round(suitability.score, 4) if suitability else None,
    }

    return PlaceExplanation(
        rank=breakdown.rank,
        primary_reason=primary_reason,
        matched_preferences=matched[:10],
        local_context=local_context,
        score_factors=score_factors,
        fairness_note=fairness_note,
        accessibility_note=accessibility_note,
        route_summary=route_summary,
        provider_source=provider_source,
        provider_status=provider_status,
        evidence_fields_used=sorted(set(evidence)),
    )

def _preference_flags(
    *,
    budget_applied: bool,
    accessibility_applied: bool,
    user_location_applied: bool,
    filtered_count: int = 0,
) -> str:
    """Build a redacted preference diagnostic string for reasoning_log."""
    parts: list[str] = []
    if budget_applied:
        parts.append("preference_budget_applied=True")
    if accessibility_applied:
        parts.append("preference_accessibility_applied=True")
    if user_location_applied:
        parts.append("user_location_applied=True")
    if filtered_count > 0:
        parts.append(f"filtered_count={filtered_count}")
    return " ".join(parts) if parts else ""


def _apply_preference_filters(
    candidates: list["PlaceCandidate"],
    request: "PlaceSearchRequest",
) -> tuple[list["PlaceCandidate"], int]:
    """Apply deterministic post-provider preference filtering and reranking.

    - Budget: exclude candidates whose price_level falls outside the requested
      budget_filter numeric range.
    - Accessibility: boost candidates with wheelchair_accessible options by
      increasing their geo_locality (so fairness balancing and reranking will tend
      to promote them) — no hard filter because accessibility metadata is often
      missing.  Candidates with unknown accessibility metadata are retained without
      hiding their unknown status.
    - User location: already used in _build_request for origin; proximity scoring
      is handled downstream by FeatureExtractor.

    Returns (filtered_candidates, count_of_excluded_by_budget).
    """
    initial_count = len(candidates)

    if not candidates:
        return candidates, 0

    result = list(candidates)

    # Budget filtering: exclude candidates whose price_level is NOT in the
    # requested numeric price levels.
    numeric_levels = request.numeric_price_levels
    if numeric_levels:
        allowed = set(numeric_levels)
        filtered = []
        for c in result:
            if c.price_level is None:
                # Keep candidates without price_level metadata (no info = no filter)
                filtered.append(c)
            elif c.price_level in allowed:
                filtered.append(c)
            # else: excluded by budget filter
        excluded_by_budget = len(result) - len(filtered)
        result = filtered
    else:
        excluded_by_budget = 0

    # Accessibility boosting: when wheelchair_accessible_preference is True,
    # promote candidates that have positive accessibility options by slightly
    # increasing their geo_locality.  This is a soft boost — accessible
    # candidates stay ahead in fairness/re-ranking but we do NOT filter out
    # candidates whose accessibility metadata is unknown.
    if request.wheelchair_accessible_preference is True:
        boosted = 0
        for c in result:
            if c.accessibility_options and any(c.accessibility_options.values()):
                # Boost geo_locality by 0.1, capped at 1.0
                c.geo_locality = min(1.0, (c.geo_locality or 0.5) + 0.1)
                boosted += 1
            # Candidates with no accessibility_options dict or all-False values
            # are left unchanged — unknown metadata is preserved, not hidden.
        if boosted > 0:
            # Sort by updated geo_locality descending so accessibility-aware
            # candidates surface higher before fairness/reranking.
            result.sort(key=lambda c: c.geo_locality or 0.0, reverse=True)

    return result, excluded_by_budget


def _maps_url(place_id: str) -> str:
    return f"https://map.goong.io/?pid={quote(place_id, safe='')}"


# -- Ham Ninh cultural/community context for commercial suggestions (R044) --

# Place type values that indicate a commercial venue (food, lodging, hospitality).
# Used to decide whether to prepend sustainable-tourism cultural context.
_COMMERCIAL_PLACE_TYPES = frozenset({
    "restaurant", "seafood_restaurant", "cafe", "bar", "meal_takeaway",
    "meal_delivery", "bakery", "food", "lodging", "hotel", "motel",
    "resort", "guest_house", "bed_and_breakfast", "hostel", "apartment",
    "homestay", "rv_park", "campground",
})

# Short Ham Ninh cultural/community prefaces — generic and safe.
# No document citations, no invented place names, no specific business claims.
_HAM_NINH_CULTURAL_PREFACE_VI = (
    "Hàm Ninh là làng chài truyền thống với cuộc sống biển đậm bản sắc. "
    "Hãy ủng hộ doanh nghiệp địa phương và tôn trọng nhịp sống ngư dân khi ghé thăm. "
)
_HAM_NINH_CULTURAL_PREFACE_EN = (
    "Ham Ninh is a traditional fishing village with a rich coastal community culture. "
    "Consider supporting local businesses and respecting the daily rhythm of fishing life when visiting. "
)


def _is_commercial_query(candidates: list["PlaceCandidate"]) -> bool:
    """Return True when any candidate carries a commercial place type.

    Covers restaurants, seafood venues, cafes, bars, hotels, homestays,
    and other hospitality/food categories. Returns False for empty lists.
    """
    if not candidates:
        return False
    for c in candidates:
        for t in (c.types or []):
            if t.lower() in _COMMERCIAL_PLACE_TYPES:
                return True
    return False


def _cultural_preface(language_code: str) -> str:
    """Return a short Ham Ninh cultural/community preface for the given language.

    Defaults to Vietnamese for unknown language codes (safe fallback).
    """
    if language_code == "en":
        return _HAM_NINH_CULTURAL_PREFACE_EN
    return _HAM_NINH_CULTURAL_PREFACE_VI


def _message_for_status(
    status: PlaceToolStatus,
    *,
    result_count: int = 0,
    is_commercial: bool = False,
    language_code: str = "vi",
    display_names: list[str] | None = None,
    frame: RecommendationFrame | None = None,
) -> str:
    if status == PlaceToolStatus.OK:
        names = [name.strip() for name in (display_names or []) if name.strip()]
        top_names = names[:3]
        if frame and frame.goal == "itinerary":
            if language_code == "en":
                if top_names:
                    joined = "; ".join(top_names)
                    return f"For this trip goal, I would start with these easier options: {joined}. I kept the list short so you can compare quickly; open the cards for map and practical details."
                return "I found a few possible stops for this trip goal. Open the cards to compare map and practical details."
            if top_names:
                joined = "; ".join(top_names)
                return f"Với mục tiêu chuyến đi này, mình ưu tiên vài điểm dễ cân nhắc trước: {joined}. Mình rút gọn danh sách để bạn so sánh nhanh; mở từng thẻ để xem bản đồ và chi tiết thực tế."
            return "Mình tìm được vài điểm có thể cân nhắc cho mục tiêu chuyến đi này. Bạn mở từng thẻ để xem bản đồ và chi tiết thực tế."
        if language_code == "en":
            if top_names:
                joined = "; ".join(top_names)
                base = f"I found {result_count} relevant places around Ham Ninh. Start with: {joined}. Open the cards for map and practical details."
            else:
                base = f"I found {result_count} relevant places around Ham Ninh. Open the cards for map and practical details."
        elif top_names:
            joined = "; ".join(top_names)
            base = f"Mình tìm được {result_count} địa điểm phù hợp quanh Hàm Ninh. Nên bắt đầu với: {joined}. Bạn mở từng thẻ để xem bản đồ và chi tiết thực tế."
        else:
            base = f"Mình tìm được {result_count} địa điểm phù hợp quanh Hàm Ninh. Bạn mở từng thẻ để xem bản đồ và chi tiết thực tế."
        if is_commercial:
            return _cultural_preface(language_code) + base
        return base
    if status == PlaceToolStatus.EMPTY:
        return "Mình chưa tìm thấy địa điểm phù hợp quanh Hàm Ninh cho yêu cầu này. Bạn thử nói rõ loại địa điểm, ngân sách hoặc khu vực gần đâu nhé."
    if status == PlaceToolStatus.CREDENTIALS_BLOCKED:
        return "Tính năng tìm địa điểm đang thiếu cấu hình Places API trên máy chủ, nên mình chưa thể trả kết quả địa điểm thật lúc này."
    if status == PlaceToolStatus.UPSTREAM_ERROR:
        return "Tính năng tìm địa điểm đang tạm lỗi và không khả dụng từ Places API. Bạn thử lại sau một chút nhé."
    if status == PlaceToolStatus.INVALID_REQUEST:
        return "Mình chưa tìm được vì yêu cầu tìm địa điểm chưa đủ rõ. Bạn thử viết ngắn hơn, ví dụ: 'nhà hàng hải sản gần Hàm Ninh'."
    return "Tính năng tìm địa điểm đang tạm không khả dụng. Bạn thử lại sau nhé."


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


FAIRNESS_LOCAL_THRESHOLD = 0.6  # geo_locality >= this counts as "local"
FAIRNESS_TOP_K = 5  # top-K window for local representation target
FAIRNESS_TOP5_TARGET_RATIO = 0.4  # target local fraction in top-K


def _is_local(result: PlaceResult) -> bool:
    """Return True when result carries a geo_locality meeting the documented threshold."""
    return (result.geo_locality or 0.0) >= FAIRNESS_LOCAL_THRESHOLD


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
    """Return True when candidate carries a geo_locality meeting the threshold."""
    return (candidate.geo_locality or 0.0) >= FAIRNESS_LOCAL_THRESHOLD


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

    # Count candidates missing geo_locality metadata
    missing_geo_locality_count = sum(
        1 for c in candidates if c.geo_locality is None
    )

    # Compute top-5 local ratio
    top_k = results[:FAIRNESS_TOP_K]
    if top_k:
        local_in_top5 = sum(
            1 for r in top_k if (r.geo_locality or 0.0) >= FAIRNESS_LOCAL_THRESHOLD
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
    if missing_geo_locality_count > 0:
        warnings.append(FairnessWarningType.MISSING_LOCAL_FACTOR_METADATA.value)

    # Check if supply limits fair representation
    local_candidates = sum(
        1 for c in candidates if (c.geo_locality or 0.0) >= FAIRNESS_LOCAL_THRESHOLD
    )
    top5_target = max(1, int(FAIRNESS_TOP_K * 0.4))  # 40% of top-5 ≈ 2
    if local_candidates < top5_target and candidate_count >= FAIRNESS_TOP_K:
        warnings.append(FairnessWarningType.INSUFFICIENT_LOCAL_CANDIDATES.value)

    return FairnessAudit(
        candidate_count=candidate_count,
        result_count=result_count,
        top5_local_ratio=round(top5_local_ratio, 4),
        missing_geo_locality_count=missing_geo_locality_count,
        provider_status=provider_status.value,
        warnings=warnings,
    )
