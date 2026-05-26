"""Tests for POST /chat endpoint wired to GroundedAnswerService."""

from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.request import LatLng
from app.models.response import ChatResponse, PlaceResult, ScoreBreakdown
from agents.tools.corpus_loader import load_corpus
from agents.tools.retriever import Retriever


@pytest.fixture()
def client():
    """TestClient that runs the lifespan (loads corpus + retriever)."""
    with TestClient(app) as c:
        yield c


class TestChatEndpointHappyPath:
    """POST /chat returns ChatResponse for valid queries."""

    def test_vi_cultural_query(self, client):
        r = client.post("/chat", json={
            "session_id": "s1",
            "message": "làng chài Hàm Ninh",
            "language": "vi",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["session_id"] == "s1"
        assert body["intent"] == "cultural_query"
        assert body["latency_ms"] > 0
        assert isinstance(body["message"], str)
        assert len(body["message"]) > 0
        assert isinstance(body["citations"], list)

    def test_en_cultural_query(self, client):
        r = client.post("/chat", json={
            "session_id": "s2",
            "message": "What is Ham Ninh fishing village?",
            "language": "en",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["intent"] == "cultural_query"
        assert body["message"].startswith("Based on")

    def test_restaurant_intent(self, client):
        r = client.post("/chat", json={
            "session_id": "s3",
            "message": "nhà hàng hải sản ngon",
            "language": "vi",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["intent"] == "place_recommendation"
        assert body["places"] == []
        assert "credential" in body["reasoning_log"] or "status=empty" in body["reasoning_log"] or "status=upstream_error" in body["reasoning_log"]

    def test_navigation_intent(self, client):
        r = client.post("/chat", json={
            "session_id": "s4",
            "message": "đường đi đến Hàm Ninh",
            "language": "vi",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["intent"] == "place_recommendation"
        assert body["places"] == []
        assert "place_recommendation status=" in body["reasoning_log"]

    def test_response_has_all_required_keys(self, client):
        r = client.post("/chat", json={
            "session_id": "s5",
            "message": "Phú Quốc",
            "language": "vi",
        })
        body = r.json()
        required = {
            "session_id", "message", "citations", "places",
            "intent", "langfuse_trace_id", "latency_ms",
        }
        assert required.issubset(body.keys())


class TestChatEndpointValidation:
    """POST /chat returns 422 for invalid payloads."""

    def test_missing_message(self, client):
        r = client.post("/chat", json={"session_id": "s6"})
        assert r.status_code == 422
        body = r.json()
        assert "message" in body["detail"].lower() or "errors" in body

    def test_missing_session_id(self, client):
        r = client.post("/chat", json={"message": "hello"})
        assert r.status_code == 422

    def test_empty_message(self, client):
        r = client.post("/chat", json={
            "session_id": "s7",
            "message": "",
            "language": "vi",
        })
        assert r.status_code == 422

    def test_invalid_language(self, client):
        r = client.post("/chat", json={
            "session_id": "s8",
            "message": "hello",
            "language": "fr",
        })
        assert r.status_code == 422



class TestChatEndpointAgentDelegation:
    def test_post_chat_calls_agent_service_answer(self, client):
        mock_agent = MagicMock()
        mock_agent.checkpoint_mode = "test"
        mock_agent.answer = AsyncMock(return_value=ChatResponse(
            session_id="agent-post-s1",
            message="agent response",
            citations=[],
            places=[PlaceResult(
                place_id="places/pin-ready",
                display_name="Pin Ready Seafood",
                formatted_address="Ham Ninh, Phu Quoc",
                location=LatLng(lat=10.1794, lng=104.0491),
                types=["restaurant", "seafood_restaurant"],
                primary_type="seafood_restaurant",
                rating=4.7,
                user_rating_count=321,
                price_level=2,
                open_now=True,
                business_status="OPERATIONAL",
                local_factor=0.8,
                final_score=0.9,
                score_breakdown=ScoreBreakdown(
                    tree1_locality=0.9,
                    tree2_proximity=0.8,
                    tree3_quality=0.85,
                    s_bag=0.85,
                    delta1_fairness=0.0,
                    delta2_access=0.0,
                    final_score=0.9,
                    rank=1,
                ),
                google_maps_uri="https://maps.example/pin-ready",
            )],
            intent="place_recommendation",
            langfuse_trace_id=None,
            latency_ms=1.0,
            fallback=False,
        ))
        app.state.agent_service = mock_agent

        r = client.post("/chat", json={
            "session_id": "agent-post-s1",
            "message": "Hàm Ninh",
            "language": "vi",
        })

        assert r.status_code == 200
        body = r.json()
        assert body["message"] == "agent response"
        assert body["places"][0]["location"] == {"lat": 10.1794, "lng": 104.0491}
        assert body["places"][0]["types"] == ["restaurant", "seafood_restaurant"]
        assert body["places"][0]["primary_type"] == "seafood_restaurant"
        assert body["places"][0]["user_rating_count"] == 321
        assert body["places"][0]["open_now"] is True
        assert body["places"][0]["business_status"] == "OPERATIONAL"
        mock_agent.answer.assert_awaited_once_with(
            session_id="agent-post-s1",
            message="Hàm Ninh",
            language="vi",
        )

class TestChatEndpointCorpusNotLoaded:
    """POST /chat returns 503 when retriever is not loaded."""

    def test_corpus_not_loaded_returns_503(self):
        """Simulate corpus load failure: endpoint returns 503 with structured error."""
        # Patch load_corpus to raise an exception, forcing the lifespan to set
        # app.state.retriever = None. Then use TestClient which runs that lifespan.
        with patch(
            "app.main.load_corpus",
            side_effect=FileNotFoundError("corpus file missing"),
        ):
            with TestClient(app) as c:
                # Confirm retriever is None after failed startup
                assert app.state.retriever is None

                r = c.post("/chat", json={
                    "session_id": "s9",
                    "message": "làng chài Hàm Ninh",
                    "language": "vi",
                })
                assert r.status_code == 503
                body = r.json()
                assert "error" in body["detail"]
                assert body["detail"]["error"] == "service_unavailable"
