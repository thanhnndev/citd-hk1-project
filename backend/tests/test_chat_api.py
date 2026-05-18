"""Comprehensive tests for POST /chat contract and no-regression suite.

Covers:
- Successful queries with citations and correct response shape
- Honest no-evidence behavior for unrecognizable queries
- Input validation (empty message, missing session_id, oversized message, invalid language)
- Language-specific responses (en vs vi)
- Intent detection via keyword matching
- 503 graceful degradation when corpus is not loaded
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure required env vars before importing app modules
for _k in ("OPENAI_API_KEY", "GOOGLE_PLACES_API_KEY", "GOOGLE_ROUTES_API_KEY"):
    os.environ.setdefault(_k, "fake-test-key")

from app.main import app
from app.models.response import ChatResponse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """TestClient that runs the lifespan (loads corpus + retriever)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def client_no_corpus():
    """TestClient with corpus load forced to fail — retriever is None."""
    with patch(
        "app.main.load_corpus",
        side_effect=FileNotFoundError("corpus file missing"),
    ):
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# TestChatEndpointSuccess
# ---------------------------------------------------------------------------

class TestChatEndpointSuccess:
    """POST /chat with cultural query returns 200, ChatResponse shape,
    non-empty message, at least 1 citation, intent set, latency_ms > 0."""

    def test_vi_cultural_query_returns_200(self, client):
        r = client.post("/chat", json={
            "session_id": "s-success-01",
            "message": "làng chài Hàm Ninh",
            "language": "vi",
        })
        assert r.status_code == 200

    def test_response_shape_matches_chat_response(self, client):
        r = client.post("/chat", json={
            "session_id": "s-success-02",
            "message": "làng chài Hàm Ninh",
            "language": "vi",
        })
        body = r.json()
        required_keys = {
            "session_id", "message", "citations", "places",
            "reasoning_log", "intent", "langfuse_trace_id", "latency_ms",
        }
        assert required_keys.issubset(body.keys())

    def test_session_id_echoed(self, client):
        sid = "s-success-03"
        r = client.post("/chat", json={
            "session_id": sid,
            "message": "Hàm Ninh",
            "language": "vi",
        })
        assert r.json()["session_id"] == sid

    def test_message_non_empty(self, client):
        r = client.post("/chat", json={
            "session_id": "s-success-04",
            "message": "Hàm Ninh",
            "language": "vi",
        })
        body = r.json()
        assert isinstance(body["message"], str)
        assert len(body["message"]) > 0

    def test_citations_present_on_hit(self, client):
        r = client.post("/chat", json={
            "session_id": "s-success-05",
            "message": "làng chài Hàm Ninh",
            "language": "vi",
        })
        body = r.json()
        assert isinstance(body["citations"], list)
        assert len(body["citations"]) >= 1
        # Each citation must have source, url, snippet fields
        cit = body["citations"][0]
        assert "source" in cit
        assert cit["source"]  # non-empty

    def test_intent_set(self, client):
        r = client.post("/chat", json={
            "session_id": "s-success-06",
            "message": "làng chài Hàm Ninh",
            "language": "vi",
        })
        body = r.json()
        assert body["intent"] is not None
        assert isinstance(body["intent"], str)

    def test_latency_ms_positive(self, client):
        r = client.post("/chat", json={
            "session_id": "s-success-07",
            "message": "làng chài Hàm Ninh",
            "language": "vi",
        })
        body = r.json()
        assert isinstance(body["latency_ms"], (int, float))
        assert body["latency_ms"] > 0

    def test_places_is_list(self, client):
        r = client.post("/chat", json={
            "session_id": "s-success-08",
            "message": "Hàm Ninh",
            "language": "vi",
        })
        body = r.json()
        assert isinstance(body["places"], list)

    def test_langfuse_trace_id_nullable(self, client):
        r = client.post("/chat", json={
            "session_id": "s-success-09",
            "message": "Hàm Ninh",
            "language": "vi",
        })
        body = r.json()
        # May be None in tests since Langfuse is optional
        assert "langfuse_trace_id" in body


# ---------------------------------------------------------------------------
# TestChatEndpointNoEvidence
# ---------------------------------------------------------------------------

class TestChatEndpointNoEvidence:
    """POST /chat with unrecognizable query returns 200, honest no-evidence
    message, empty citations list."""

    def test_gibberish_query_returns_200(self, client):
        r = client.post("/chat", json={
            "session_id": "s-noev-01",
            "message": "xyzabc123",
            "language": "vi",
        })
        assert r.status_code == 200

    def test_no_evidence_message_vi(self, client):
        r = client.post("/chat", json={
            "session_id": "s-noev-02",
            "message": "xyzabc123",
            "language": "vi",
        })
        body = r.json()
        assert "chưa có thông tin" in body["message"]

    def test_no_evidence_message_en(self, client):
        r = client.post("/chat", json={
            "session_id": "s-noev-03",
            "message": "xyzabc123",
            "language": "en",
        })
        body = r.json()
        assert "do not have sufficient information" in body["message"]

    def test_no_evidence_empty_citations(self, client):
        r = client.post("/chat", json={
            "session_id": "s-noev-04",
            "message": "xyzabc123",
            "language": "vi",
        })
        body = r.json()
        assert body["citations"] == []

    def test_no_evidence_empty_places(self, client):
        r = client.post("/chat", json={
            "session_id": "s-noev-05",
            "message": "xyzabc123",
            "language": "vi",
        })
        body = r.json()
        assert body["places"] == []

    def test_no_evidence_intent_still_set(self, client):
        r = client.post("/chat", json={
            "session_id": "s-noev-06",
            "message": "xyzabc123",
            "language": "vi",
        })
        body = r.json()
        # Intent still detected (will be cultural_query for gibberish)
        assert body["intent"] is not None

    def test_no_evidence_latency_present(self, client):
        r = client.post("/chat", json={
            "session_id": "s-noev-07",
            "message": "xyzabc123",
            "language": "vi",
        })
        body = r.json()
        assert body["latency_ms"] > 0

    def test_no_evidence_vi_no_fabricated_claims(self, client):
        """No-evidence messages must not contain any factual claims."""
        r = client.post("/chat", json={
            "session_id": "s-noev-08",
            "message": "qwerty",
            "language": "vi",
        })
        body = r.json()
        msg = body["message"]
        # Must NOT contain tourism facts
        for forbidden in ("Hàm Ninh", "hải sản", "Phú Quốc", "làng chài"):
            assert forbidden not in msg

    def test_no_evidence_en_no_fabricated_claims(self, client):
        """English no-evidence must not contain any factual claims."""
        r = client.post("/chat", json={
            "session_id": "s-noev-09",
            "message": "qwerty",
            "language": "en",
        })
        body = r.json()
        msg = body["message"]
        for forbidden in ("Ham Ninh", "seafood", "Phu Quoc", "fishing village"):
            assert forbidden.lower() not in msg.lower()


# ---------------------------------------------------------------------------
# TestChatEndpointValidation
# ---------------------------------------------------------------------------

class TestChatEndpointValidation:
    """POST /chat with invalid inputs returns 422."""

    def test_empty_message_returns_422(self, client):
        r = client.post("/chat", json={
            "session_id": "s-val-01",
            "message": "",
            "language": "vi",
        })
        assert r.status_code == 422

    def test_missing_session_id_returns_422(self, client):
        r = client.post("/chat", json={
            "message": "hello",
        })
        assert r.status_code == 422

    def test_message_over_2000_chars_returns_422(self, client):
        r = client.post("/chat", json={
            "session_id": "s-val-03",
            "message": "A" * 2001,
            "language": "vi",
        })
        assert r.status_code == 422

    def test_invalid_language_returns_422(self, client):
        r = client.post("/chat", json={
            "session_id": "s-val-04",
            "message": "hello",
            "language": "fr",
        })
        assert r.status_code == 422

    def test_missing_message_returns_422(self, client):
        r = client.post("/chat", json={"session_id": "s-val-05"})
        assert r.status_code == 422

    def test_empty_body_returns_422(self, client):
        r = client.post("/chat", json={})
        assert r.status_code == 422

    def test_session_id_empty_string_returns_422(self, client):
        r = client.post("/chat", json={
            "session_id": "",
            "message": "hello",
        })
        assert r.status_code == 422

    def test_message_exactly_2000_chars_accepted(self, client):
        r = client.post("/chat", json={
            "session_id": "s-val-08",
            "message": "A" * 2000,
            "language": "vi",
        })
        # Boundary: 2000 chars is valid
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# TestChatEndpointLanguage
# ---------------------------------------------------------------------------

class TestChatEndpointLanguage:
    """POST /chat with language="en" returns English-framed answer;
    language="vi" returns Vietnamese answer."""

    def test_vi_response_starts_vietnamese(self, client):
        r = client.post("/chat", json={
            "session_id": "s-lang-01",
            "message": "làng chài Hàm Ninh",
            "language": "vi",
        })
        body = r.json()
        # Vietnamese answers start with "Theo" or "Dựa trên"
        assert body["message"].startswith("Theo") or body["message"].startswith("Dựa trên"), \
            f"Expected VI framing, got: {body['message'][:40]}"

    def test_en_response_starts_english(self, client):
        r = client.post("/chat", json={
            "session_id": "s-lang-02",
            "message": "làng chài Hàm Ninh",
            "language": "en",
        })
        body = r.json()
        # English answers start with "Based on"
        assert body["message"].startswith("Based on"), \
            f"Expected EN framing, got: {body['message'][:40]}"

    def test_vi_no_evidence_has_vi_text(self, client):
        r = client.post("/chat", json={
            "session_id": "s-lang-03",
            "message": "xyzabc123",
            "language": "vi",
        })
        body = r.json()
        assert "chưa có thông tin" in body["message"]

    def test_en_no_evidence_has_en_text(self, client):
        r = client.post("/chat", json={
            "session_id": "s-lang-04",
            "message": "xyzabc123",
            "language": "en",
        })
        body = r.json()
        assert "do not have sufficient information" in body["message"]

    def test_default_language_is_vi(self, client):
        """When language field is omitted, default is Vietnamese."""
        r = client.post("/chat", json={
            "session_id": "s-lang-05",
            "message": "làng chài Hàm Ninh",
        })
        body = r.json()
        assert r.status_code == 200
        assert body["message"].startswith("Theo") or body["message"].startswith("Dựa trên"), \
            f"Expected default VI framing, got: {body['message'][:40]}"


# ---------------------------------------------------------------------------
# TestChatEndpointIntent
# ---------------------------------------------------------------------------

class TestChatEndpointIntent:
    """Verify intent detection via POST /chat:
    restaurant keywords → restaurant_search,
    cultural keywords → cultural_query,
    short/gibberish → cultural_query (default for non-keyword queries >= 3 chars)."""

    def test_restaurant_keyword_nhà_hàng(self, client):
        r = client.post("/chat", json={
            "session_id": "s-intent-01",
            "message": "nhà hàng ngon ở Hàm Ninh",
            "language": "vi",
        })
        assert r.json()["intent"] == "restaurant_search"

    def test_restaurant_keyword_hải_sản(self, client):
        r = client.post("/chat", json={
            "session_id": "s-intent-02",
            "message": "ăn hải sản Phú Quốc",
            "language": "vi",
        })
        assert r.json()["intent"] == "restaurant_search"

    def test_restaurant_english_keyword(self, client):
        r = client.post("/chat", json={
            "session_id": "s-intent-03",
            "message": "best seafood restaurant near me",
            "language": "en",
        })
        assert r.json()["intent"] == "restaurant_search"

    def test_cultural_query_default(self, client):
        """A general tourism query with no specific keywords → cultural_query."""
        r = client.post("/chat", json={
            "session_id": "s-intent-04",
            "message": "Hàm Ninh có gì thú vị?",
            "language": "vi",
        })
        assert r.json()["intent"] == "cultural_query"

    def test_cultural_query_history(self, client):
        r = client.post("/chat", json={
            "session_id": "s-intent-05",
            "message": "lịch sử làng chài Hàm Ninh",
            "language": "vi",
        })
        assert r.json()["intent"] == "cultural_query"

    def test_gibberish_maps_to_cultural_query(self, client):
        """Gibberish >= 3 chars defaults to cultural_query (not unknown)."""
        r = client.post("/chat", json={
            "session_id": "s-intent-06",
            "message": "xyzabc123",
            "language": "vi",
        })
        assert r.json()["intent"] == "cultural_query"

    def test_short_query_unknown_intent_in_service(self, client):
        """Very short queries (< 3 chars) are classified as 'unknown' in the service.
        This tests the detect_intent function directly via the response."""
        # Even through the API, the service classifies short queries
        r = client.post("/chat", json={
            "session_id": "s-intent-07",
            "message": "ab",
            "language": "vi",
        })
        body = r.json()
        # The API-level test still gets an intent from the service
        assert body["intent"] == "unknown"


# ---------------------------------------------------------------------------
# TestChatEndpointCorpusNotLoaded
# ---------------------------------------------------------------------------

class TestChatEndpointCorpusNotLoaded:
    """Test 503 behavior when app.state.retriever is not set."""

    def test_corpus_not_loaded_returns_503(self, client_no_corpus):
        """When corpus fails to load, POST /chat returns 503."""
        r = client_no_corpus.post("/chat", json={
            "session_id": "s-503-01",
            "message": "làng chài Hàm Ninh",
            "language": "vi",
        })
        assert r.status_code == 503

    def test_503_structured_error_shape(self, client_no_corpus):
        """503 response contains structured error detail."""
        r = client_no_corpus.post("/chat", json={
            "session_id": "s-503-02",
            "message": "làng chài Hàm Ninh",
            "language": "vi",
        })
        body = r.json()
        assert "detail" in body
        assert body["detail"]["error"] == "service_unavailable"

    def test_503_includes_session_id(self, client_no_corpus):
        """503 error echoes the session_id for correlation."""
        sid = "s-503-03"
        r = client_no_corpus.post("/chat", json={
            "session_id": sid,
            "message": "làng chài Hàm Ninh",
            "language": "vi",
        })
        body = r.json()
        assert body["detail"]["session_id"] == sid

    def test_503_has_descriptive_message(self, client_no_corpus):
        """503 error includes a human-readable message."""
        r = client_no_corpus.post("/chat", json={
            "session_id": "s-503-04",
            "message": "làng chài Hàm Ninh",
            "language": "vi",
        })
        body = r.json()
        assert "message" in body["detail"]
        assert "Corpus" in body["detail"]["message"] or "corpus" in body["detail"]["message"]

    def test_503_various_queries(self, client_no_corpus):
        """Any query returns 503 when corpus is not loaded."""
        queries = [
            "nhà hàng hải sản",
            "xyzabc123",
            "đường đi Hàm Ninh",
        ]
        for i, q in enumerate(queries):
            r = client_no_corpus.post("/chat", json={
                "session_id": f"s-503-05-{i}",
                "message": q,
                "language": "vi",
            })
            assert r.status_code == 503, f"Expected 503 for query: {q}"
