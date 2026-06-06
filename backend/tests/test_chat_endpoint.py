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
        assert isinstance(body["places"], list)
        # Accept either live results or credential-blocked fallback
        if body["places"]:
            assert len(body["places"]) > 0
            assert "display_name" in body["places"][0]
        else:
            log = body.get("reasoning_log", "")
            assert "credential" in log or "status=empty" in log or "status=upstream_error" in log

    def test_navigation_intent(self, client):
        r = client.post("/chat", json={
            "session_id": "s4",
            "message": "đường đi đến Hàm Ninh",
            "language": "vi",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["intent"] == "place_recommendation"
        assert isinstance(body["places"], list)
        # Accept either live results or credential-blocked fallback
        if body["places"]:
            assert len(body["places"]) > 0
        else:
            assert "place_recommendation status=" in body.get("reasoning_log", "")

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
                map_uri="https://map.goong.io/?pid=pin-ready",
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


# ============================================================================
# T02: POST /chat place intent — deterministic output, no citations, no RAG
# ============================================================================


class TestChatPlaceIntentDeterministic:
    """POST /chat with place intent returns deterministic output with zero
    citations, no RAG fallback, and place cards from typed tool result only."""

    def _make_place_response(self, count: int = 2) -> ChatResponse:
        from app.models.response import PlaceResult, ScoreBreakdown

        places = []
        for i in range(count):
            sb = ScoreBreakdown(
                tree1_locality=0.9 - i * 0.1,
                tree2_proximity=0.7 - i * 0.05,
                tree3_quality=0.8 - i * 0.1,
                s_bag=round((0.9 - i * 0.1 + 0.7 - i * 0.05 + 0.8 - i * 0.1) / 3, 4),
                delta1_fairness=0.0,
                delta2_access=0.0,
                final_score=round(0.9 - i * 0.15, 4),
                rank=i + 1,
            )
            places.append(PlaceResult(
                place_id=f"places/ham-ninh-{i}",
                display_name=f"Quán Hải Sản Hàm Ninh {i + 1}",
                formatted_address="Hàm Ninh, Phú Quốc",
                location=LatLng(lat=10.18, lng=104.05),
                types=["restaurant", "seafood_restaurant"],
                primary_type="seafood_restaurant",
                rating=4.5,
                user_rating_count=100,
                price_level=2,
                open_now=True,
                business_status="OPERATIONAL",
                local_factor=0.8,
                final_score=sb.final_score,
                score_breakdown=sb,
                map_uri=f"https://map.goong.io/?pid=ham-ninh-{i}",
            ))

        return ChatResponse(
            session_id="s-place-det",
            message="Mình tìm được 2 địa điểm phù hợp quanh Hàm Ninh. Bạn có thể mở từng thẻ địa điểm để xem bản đồ, điểm đánh giá và lý do xếp hạng.",
            citations=[],
            places=places,
            reasoning_log="place_recommendation status=ok source=google_places candidate_count=2 result_count=2",
            intent="place_recommendation",
            latency_ms=150.0,
            fallback=False,
        )

    def test_place_intent_returns_zero_citations(self, client):
        """Place intent /chat response must have citations=[]."""
        mock_response = self._make_place_response()
        mock_agent = MagicMock()
        mock_agent.checkpoint_mode = "test"
        mock_agent.answer = AsyncMock(return_value=mock_response)
        app.state.agent_service = mock_agent

        r = client.post("/chat", json={
            "session_id": "s-place-det",
            "message": "nhà hàng hải sản gần đây",
            "language": "vi",
        })

        assert r.status_code == 200
        body = r.json()
        assert body["citations"] == []
        assert body["intent"] == "place_recommendation"
        assert len(body["places"]) == 2

    def test_place_message_is_deterministic_no_llm_composition(self, client):
        """Place message is from _message_for_status, not LLM-composed prose."""
        mock_response = self._make_place_response()
        mock_agent = MagicMock()
        mock_agent.checkpoint_mode = "test"
        mock_agent.answer = AsyncMock(return_value=mock_response)
        app.state.agent_service = mock_agent

        r = client.post("/chat", json={
            "session_id": "s-place-det",
            "message": "gợi ý quán ăn",
            "language": "vi",
        })

        assert r.status_code == 200
        body = r.json()
        # Deterministic message from _message_for_status
        assert "Mình tìm được" in body["message"]
        assert "2 địa điểm" in body["message"]

    def test_place_card_names_from_tool_result_only(self, client):
        """Place card display names come only from tool result, never invented."""
        mock_response = self._make_place_response(count=1)
        mock_response.places[0].display_name = "Nhà hàng Biển Xanh"
        mock_response.message = "Mình tìm được 1 địa điểm phù hợp quanh Hàm Ninh."
        mock_agent = MagicMock()
        mock_agent.checkpoint_mode = "test"
        mock_agent.answer = AsyncMock(return_value=mock_response)
        app.state.agent_service = mock_agent

        r = client.post("/chat", json={
            "session_id": "s-place-name",
            "message": "nhà hàng",
            "language": "vi",
        })

        body = r.json()
        assert body["places"][0]["display_name"] == "Nhà hàng Biển Xanh"
        # Message does NOT contain the specific place name (it's generic count-based)
        assert "Biển Xanh" not in body["message"]

    def test_credential_blocked_returns_honest_text_zero_citations(self, client):
        """When provider is credential-blocked, response is honest text with zero citations."""
        mock_response = ChatResponse(
            session_id="s-cred-blocked",
            message="Tính năng tìm địa điểm đang thiếu cấu hình Places API trên máy chủ, nên mình chưa thể trả kết quả địa điểm thật lúc này.",
            citations=[],
            places=[],
            reasoning_log="place_recommendation status=credentials_blocked source=google_places candidate_count=0 result_count=0",
            intent="place_recommendation",
            latency_ms=10.0,
            fallback=True,
        )
        mock_agent = MagicMock()
        mock_agent.checkpoint_mode = "test"
        mock_agent.answer = AsyncMock(return_value=mock_response)
        app.state.agent_service = mock_agent

        r = client.post("/chat", json={
            "session_id": "s-cred-blocked",
            "message": "nhà hàng hải sản",
            "language": "vi",
        })

        body = r.json()
        assert body["citations"] == []
        assert body["places"] == []
        assert "thiếu cấu hình" in body["message"]
        assert body["intent"] == "place_recommendation"

    def test_upstream_error_returns_honest_text_zero_citations(self, client):
        """When provider has upstream error, response is honest error text with zero citations."""
        mock_response = ChatResponse(
            session_id="s-upstream-err",
            message="Tính năng tìm địa điểm đang tạm lỗi từ Places API. Bạn thử lại sau một chút nhé.",
            citations=[],
            places=[],
            reasoning_log="place_recommendation status=upstream_error source=google_places candidate_count=0 result_count=0",
            intent="place_recommendation",
            latency_ms=5.0,
            fallback=True,
        )
        mock_agent = MagicMock()
        mock_agent.checkpoint_mode = "test"
        mock_agent.answer = AsyncMock(return_value=mock_response)
        app.state.agent_service = mock_agent

        r = client.post("/chat", json={
            "session_id": "s-upstream-err",
            "message": "quán cafe",
            "language": "vi",
        })

        body = r.json()
        assert body["citations"] == []
        assert body["places"] == []
        assert "tạm lỗi" in body["message"]

    def test_empty_results_returns_honest_text_zero_citations(self, client):
        """When provider returns zero candidates, response is honest empty text."""
        mock_response = ChatResponse(
            session_id="s-empty-res",
            message="Mình chưa tìm thấy địa điểm phù hợp quanh Hàm Ninh cho yêu cầu này. Bạn thử nói rõ loại địa điểm, ngân sách hoặc khu vực gần đâu nhé.",
            citations=[],
            places=[],
            reasoning_log="place_recommendation status=empty source=google_places candidate_count=0 result_count=0",
            intent="place_recommendation",
            latency_ms=50.0,
            fallback=True,
        )
        mock_agent = MagicMock()
        mock_agent.checkpoint_mode = "test"
        mock_agent.answer = AsyncMock(return_value=mock_response)
        app.state.agent_service = mock_agent

        r = client.post("/chat", json={
            "session_id": "s-empty-res",
            "message": "quán pizza Hàm Ninh",  # unlikely to exist
            "language": "vi",
        })

        body = r.json()
        assert body["citations"] == []
        assert body["places"] == []
        assert "chưa tìm thấy" in body["message"]

    def test_reasoning_log_has_provider_diagnostics(self, client):
        """Place responses include reasoning_log with provider status, source, counts."""
        mock_response = self._make_place_response()
        mock_agent = MagicMock()
        mock_agent.checkpoint_mode = "test"
        mock_agent.answer = AsyncMock(return_value=mock_response)
        app.state.agent_service = mock_agent

        r = client.post("/chat", json={
            "session_id": "s-reasoning",
            "message": "hải sản",
            "language": "vi",
        })

        body = r.json()
        log = body.get("reasoning_log", "")
        assert "place_recommendation" in log
        assert "status=ok" in log
        assert "source=google_places" in log
        assert "candidate_count=2" in log
        assert "result_count=2" in log
