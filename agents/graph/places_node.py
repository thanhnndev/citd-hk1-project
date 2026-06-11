from __future__ import annotations

import hashlib
import inspect
import json
import math
import time
from typing import Any, Literal

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from app.models.rag import RAGChunk
from app.models.response import Citation
from agents.graph.state import AgentState, RouterOutput
from agents.guardrails.input_guardrails import block_injection, reject_off_topic
from agents.guardrails.output_guardrails import verify_grounding
from agents.graph.routing import (_clarify_message, _direct_answer, _extract_suggestions, _fallback_action, _get_default_suggestions, _messages_for_llm)
from agents.tools.retriever import citation_from_chunk
from agents.graph.dependencies import NodeServices, configure_services, get_services
from agents.graph.helpers import *

logger = structlog.get_logger(__name__)
# 6. maps_agent_node
# ---------------------------------------------------------------------------


async def maps_agent_node(state: AgentState, config: RunnableConfig = None) -> dict[str, Any]:
    """Maps agent node: call PlaceRecommendationService for place recommendations.

    Calls the injected PlaceRecommendationService to retrieve fairness-ranked
    places with score_breakdown. Handles location consent and service failures
    gracefully.

    Reads:
        - ``state["message"]`` — user query text
        - ``state["user_location"]`` — optional dict with lat/lng
        - ``state["language"]`` — language code (default "vi")
        - ``state["session_id"]`` — session identifier
        - ``state["needs_location"]`` — whether location is required
    Writes:
        - ``places`` — list of place dicts with score_breakdown
        - ``response_text`` — natural language response message
    """
    t0 = time.perf_counter()
    session_id = state.get("session_id", "")
    message = state.get("message", "")
    language = state.get("language", "vi")
    needs_location = state.get("needs_location", False)

    # Best practice: Retrieve static configuration parameters from RunnableConfig if available,
    # falling back to AgentState for backward compatibility.
    configurable = config.get("configurable", {}) if config else {}
    user_location = configurable.get("user_location") or state.get("user_location")
    if not needs_location:
        user_location = None
    budget_filter = configurable.get("budget_filter") or state.get("budget_filter")
    accessibility_required = bool(
        configurable.get("accessibility_required", state.get("accessibility_required", False))
        or _requests_accessibility(message)
    )

    logger.info(
        "graph.node_enter",
        node="maps_agent",
        session_id=session_id,
        mode="place_recommendation",
    )

    if _is_place_comparison_followup(message, state):
        return _compare_previous_places(state)

    missing_context_followup = _clarify_decision_followup_without_context(state)
    if missing_context_followup is not None:
        return missing_context_followup

    decision_followup = _answer_place_decision_followup(state)
    if decision_followup is not None:
        return decision_followup

    # Location consent: use interrupt() pattern per LangGraph docs
    # Frontend will detect interrupt, request geolocation, and resume with Command(resume=user_location)
    if needs_location and user_location is None:
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="maps_agent",
            session_id=session_id,
            mode="location_interrupt",
            duration_ms=elapsed,
        )
        # Pause graph and request location from frontend
        user_location = interrupt({
            "type": "location_request",
            "message": (
                "Để gợi ý địa điểm phù hợp gần bạn, mình cần biết vị trí hiện tại. "
                "Trình duyệt sẽ yêu cầu quyền truy cập vị trí."
                if language == "vi"
                else "To recommend places near you, I need your current location. "
                "The browser will request location permission."
            ),
            "requires_geolocation": True,
        })
        # After resume, user_location will be populated with the resume payload.
        logger.info(
            "graph.node_resume",
            node="maps_agent",
            session_id=session_id,
            location_received=user_location is not None,
        )

    if needs_location and (
        not isinstance(user_location, dict)
        or not isinstance(user_location.get("lat"), (int, float))
        or not isinstance(user_location.get("lng"), (int, float))
    ):
        response_text = (
            "Mình chưa có vị trí hiện tại nên chưa thể xếp hạng các quán gần bạn. "
            "Bạn có thể bật quyền vị trí, hoặc hỏi cụ thể theo khu vực như 'quán hải sản ở Hàm Ninh'."
            if language == "vi"
            else "I do not have your current location, so I cannot rank nearby places yet. "
            "You can enable location access or ask for a specific area such as seafood restaurants in Ham Ninh."
        )
        return {
            "places": [],
            "response_text": response_text,
            "suggestions": (
                ["Quán hải sản ở Hàm Ninh", "Tìm gần chợ Hàm Ninh", "Bật vị trí rồi thử lại"]
                if language == "vi"
                else ["Seafood in Ham Ninh", "Find near Ham Ninh market", "Enable location and retry"]
            ),
            "intent": state.get("intent") or "restaurant_search",
        }

    # Get PlaceRecommendationService from dependency injection
    services = get_services()
    places_service = services.places_service

    if places_service is None:
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.warning(
            "graph.node_exit",
            node="maps_agent",
            session_id=session_id,
            mode="no_places_service",
            duration_ms=elapsed,
        )
        error_message = (
            "Xin lỗi, dịch vụ gợi ý địa điểm hiện không khả dụng. "
            "Vui lòng thử lại sau."
            if language == "vi"
            else "Sorry, the place recommendation service is currently unavailable. "
            "Please try again later."
        )
        return {
            "places": [],
            "response_text": error_message,
        }

    # Call PlaceRecommendationService
    try:
        chat_response = await places_service.recommend(
            query=message,
            user_location=user_location,
            language=language,
            session_id=session_id,
            budget=budget_filter,
            accessibility=accessibility_required,
        )

        # Convert PlaceResult Pydantic models to dicts for AgentState
        places_dicts = [place.model_dump() for place in chat_response.places]

        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "graph.node_exit",
            node="maps_agent",
            session_id=session_id,
            mode="place_recommendation",
            place_count=len(places_dicts),
            duration_ms=elapsed,
        )

        return {
            "places": places_dicts,
            "response_text": chat_response.message,
            "intent": chat_response.intent or state.get("intent") or "restaurant_search",
            "run_status": "gathering",
            "current_step": "places",
            "tool_receipts": [{
                "tool": "place_recommendation",
                "status": "success",
                "result_count": len(places_dicts),
            }],
            "last_places": places_dicts,
            "last_place_query": message,
            "last_place_included_type": (
                "cafe"
                if any(term in message.lower() for term in ("cà phê", "cafe", "coffee", "quán cf"))
                else None
            ),
            "last_place_accessibility_required": accessibility_required,
            "last_place_user_location": user_location,
        }

    except Exception as exc:
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        logger.error(
            "graph.node_exit",
            node="maps_agent",
            session_id=session_id,
            mode="service_error",
            error_type=type(exc).__name__,
            error=str(exc),
            duration_ms=elapsed,
        )
        error_message = (
            "Xin lỗi, đã xảy ra lỗi khi tìm kiếm địa điểm. "
            "Vui lòng thử lại sau."
            if language == "vi"
            else "Sorry, an error occurred while searching for places. "
            "Please try again later."
        )
        return {
            "places": [],
            "response_text": error_message,
        }
