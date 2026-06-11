"""Focused tests for the single HamNinhGraph workflow."""

from contextlib import asynccontextmanager
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
from agents.graph.tracing import GraphTrace, trace_graph_turn


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
        "__error_handler__output_guardrails",
    }



def test_new_turn_resets_turn_scoped_outputs():
    state = HamNinhGraph._new_turn_state(
        session_id="session",
        message="hello",
        language="vi",
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


@pytest.mark.asyncio
async def test_answer_groups_graph_under_one_trace_and_returns_trace_id():
    graph = HamNinhGraph(checkpointer=InMemorySaver())
    graph.graph = MagicMock()
    final_state = {
        "response_text": "Ẩm thực Hàm Ninh",
        "intent": "food_culture",
        "citations": [],
        "places": [],
        "suggestions": [],
        "guardrail_flags": {},
    }
    graph.graph.ainvoke = AsyncMock(return_value=final_state)
    observation = MagicMock()

    @asynccontextmanager
    async def fake_trace(**_kwargs):
        yield GraphTrace(
            config={"callbacks": ["langfuse-handler"]},
            trace_id="trace-123",
            observation=observation,
        )

    with patch("agents.graph.ham_ninh_graph.trace_graph_turn", fake_trace):
        result = await graph.answer(
            session_id="session-123",
            message="Kể về ẩm thực địa phương",
        )

    config = graph.graph.ainvoke.call_args.args[1]
    assert config["callbacks"] == ["langfuse-handler"]
    assert config["configurable"]["thread_id"] == "session-123"
    assert result.langfuse_trace_id == "trace-123"
    observation.update.assert_called_once()
    traced_output = observation.update.call_args.kwargs["output"]
    assert traced_output["response"] == "Ẩm thực Hàm Ninh"
    assert traced_output["state"]["intent"] == "food_culture"


@pytest.mark.asyncio
async def test_langfuse_turn_builds_root_trace_and_langgraph_callback():
    client = MagicMock()
    observation = MagicMock()
    client.start_as_current_observation.return_value.__enter__.return_value = observation
    client.get_current_trace_id.return_value = "trace-root"
    handler = MagicMock()

    with patch("langfuse.langchain.CallbackHandler", return_value=handler):
        async with trace_graph_turn(
            langfuse_client=client,
            session_id="session-123",
            operation="answer",
            input_data={"message": "Kể về ẩm thực địa phương"},
        ) as trace:
            assert trace.trace_id == "trace-root"
            assert trace.config["callbacks"] == [handler]
            trace.finish({"response_text": "Câu trả lời", "current_step": "completed"})

    client.start_as_current_observation.assert_called_once_with(
        name="ham-ninh-request",
        as_type="agent",
        input={"message": "Kể về ẩm thực địa phương"},
        metadata={"operation": "answer"},
    )
    observation.set_trace_io.assert_any_call(
        input={"message": "Kể về ẩm thực địa phương"}
    )
    observation.set_trace_io.assert_any_call(
        output={
            "response": "Câu trả lời",
            "state": {
                "response_text": "Câu trả lời",
                "current_step": "completed",
                },
            }
        )


@pytest.mark.asyncio
async def test_output_guardrails_soft_timeout():
    from langgraph.errors import NodeError, NodeTimeoutError
    from agents.graph.ham_ninh_graph import output_guardrails_error_handler
    
    state = {
        "session_id": "test_session",
        "response_text": "Generated answer",
        "guardrail_flags": {},
    }
    
    # Create a NodeTimeoutError and wrap it in NodeError
    timeout_exc = NodeTimeoutError(node="output_guardrails", elapsed=1.5, kind="run", run_timeout=1.0)
    node_error = NodeError(node="output_guardrails", error=timeout_exc)

    
    # Call the error handler
    result = output_guardrails_error_handler(state, node_error)
    
    # Check that it did not raise an error, but returned a degraded state update
    assert "guardrail_flags" in result
    assert result["guardrail_flags"]["output_grounding"]["verdict"] == "degraded"
    assert result["guardrail_flags"]["output_grounding"]["reason"] == "timeout"
    assert "messages" in result
    assert result["messages"][0]["content"] == "Generated answer"


