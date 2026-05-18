"""Tests for POST /chat endpoint wired to GroundedAnswerService."""

from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.corpus_loader import load_corpus
from app.services.retriever import Retriever


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
        assert r.json()["intent"] == "restaurant_search"

    def test_navigation_intent(self, client):
        r = client.post("/chat", json={
            "session_id": "s4",
            "message": "đường đi đến Hàm Ninh",
            "language": "vi",
        })
        assert r.status_code == 200
        assert r.json()["intent"] == "navigation"

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
