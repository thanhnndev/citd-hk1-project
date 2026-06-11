"""Focused tests for the single HamNinhGraph workflow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agents.graph.ham_ninh_graph import HamNinhGraph
from agents.graph.nodes import (
    NodeServices,
    configure_services,
    intent_router_node,
    maps_agent_node,
    rag_agent_node,
    requires_user_location_heuristic,
)


def test_graph_has_only_required_nodes():
    graph = HamNinhGraph(checkpointer=InMemorySaver())
    nodes = set(graph.graph.get_graph().nodes)
    assert nodes == {
        "__start__",
        "__end__",
        "input_guardrails",
        "intent_router",
        "conversational",
        "knowledge",
        "places",
        "output_guardrails",
    }


def test_new_turn_resets_turn_scoped_outputs():
    state = HamNinhGraph._new_turn_state(
        session_id="session",
        message="hello",
        language="vi",
        history=[],
        user_location=None,
        budget_filter=None,
        accessibility_required=False,
    )
    assert state["response_text"] == ""
    assert state["places"] == []
    assert state["citations"] == []
    assert state["suggestions"] == []
    assert state["tool_receipts"] == []
    assert state["pending_input"] is None


def test_location_policy_only_uses_personal_position():
    assert requires_user_location_heuristic("Tìm quán gần tôi") is True
    assert requires_user_location_heuristic("Tìm quán gần biển Hàm Ninh") is False


@pytest.mark.asyncio
async def test_family_question_routes_to_grounded_places_without_llm():
    configure_services(NodeServices(llm_client=None))
    result = await intent_router_node({
        "session_id": "family",
        "message": "Đi với trẻ em nên ghé đâu?",
        "language": "vi",
        "history": [],
        "messages": [],
    })
    assert result["intent"] == "restaurant_search"
    assert result["current_step"] == "places"


@pytest.mark.asyncio
async def test_places_interrupts_when_current_location_is_required():
    service = AsyncMock()
    service.recommend.return_value = MagicMock(
        places=[],
        message="Không có kết quả",
        intent="restaurant_search",
    )
    configure_services(NodeServices(places_service=service))
    with patch("agents.graph.places_node.interrupt", return_value={"lat": 10.0, "lng": 103.0}) as call:
        await maps_agent_node({
            "session_id": "nearby",
            "message": "Tìm quán gần tôi",
            "language": "vi",
            "needs_location": True,
        })
    call.assert_called_once()
    service.recommend.assert_awaited_once()


@pytest.mark.asyncio
async def test_comparison_reuses_previous_candidates():
    service = AsyncMock()
    configure_services(NodeServices(places_service=service))
    result = await maps_agent_node({
        "session_id": "compare",
        "message": "quán nào gần hơn?",
        "language": "vi",
        "last_place_user_location": {"lat": 10.0, "lng": 103.0},
        "last_places": [
            {
                "place_id": "far",
                "display_name": "Xa",
                "route_distance_meters": 1000,
            },
            {
                "place_id": "near",
                "display_name": "Gần",
                "route_distance_meters": 100,
            },
        ],
    })
    service.recommend.assert_not_awaited()
    assert result["places"][0]["place_id"] == "near"


@pytest.mark.asyncio
async def test_knowledge_without_evidence_is_transparent():
    configure_services(NodeServices(retriever=None, llm_answer_service=None))

    result = await rag_agent_node({
        "session_id": "no-evidence",
        "message": "Kể về một tập tục chưa có trong dữ liệu",
        "language": "vi",
    })

    assert result["citations"] == []
    assert "chưa có thông tin cụ thể" in result["response_text"]
    assert result["tool_receipts"][0]["result_count"] == 0


@pytest.mark.asyncio
async def test_resume_uses_same_langgraph_thread_id():
    graph = HamNinhGraph(checkpointer=InMemorySaver())
    graph.graph = MagicMock()
    graph.graph.ainvoke = AsyncMock(return_value={
        "response_text": "resumed",
        "intent": "restaurant_search",
    })

    result = await graph.resume(
        session_id="thread-123",
        resume_value={"lat": 10.0, "lng": 103.0},
    )

    config = graph.graph.ainvoke.call_args.args[1]
    assert config["configurable"]["thread_id"] == "thread-123"
    assert result.response_text == "resumed"
