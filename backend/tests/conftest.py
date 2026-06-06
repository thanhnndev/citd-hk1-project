"""Shared pytest fixtures for corpus and retrieval tests."""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.tools.corpus_loader import load_corpus
from agents.tools.retriever import Retriever
from agents.tools.qdrant_service import QdrantService
from agents.tools.embedding_service import EmbeddingService

# Ensure required app secrets and local-only rate-limit storage are set before
# any app module imports.
os.environ["OPENAI_API_KEY"] = "fake-test-key"
os.environ.setdefault("REDIS_URL", "memory://")
os.environ.setdefault("RATE_LIMIT_CHAT", "10000/minute")

# ---------------------------------------------------------------------------
# Mock OpenAI client — prevents real API calls during TestClient(app) lifespan
# ---------------------------------------------------------------------------
# The app's lifespan creates LLMAnswerService which instantiates
# openai.AsyncOpenAI. We patch it before any test imports app.main so
# that the lifespan gets a mock client instead of hitting the real API.
# ---------------------------------------------------------------------------

def _make_mock_completion(content: str = "Test response", tokens: int = 50) -> MagicMock:
    """Build a mock OpenAI chat.completions.create response."""
    usage = MagicMock()
    usage.total_tokens = tokens
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    completion = MagicMock()
    completion.choices = [choice]
    completion.usage = usage
    return completion


def _make_tool_call_completion(tool_name: str, arguments: str, tokens: int = 30) -> MagicMock:
    """Build a mock OpenAI response with tool_calls."""
    usage = MagicMock()
    usage.total_tokens = tokens
    tool_call = MagicMock()
    tool_call.id = "tc-mock-001"
    tool_call.type = "function"
    tool_call.function = MagicMock()
    tool_call.function.name = tool_name
    tool_call.function.arguments = arguments
    message = MagicMock()
    message.content = None
    message.tool_calls = [tool_call]
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = "tool_calls"
    completion = MagicMock()
    completion.choices = [choice]
    completion.usage = usage
    return completion


_PLACE_KEYWORDS_VI = ("nhà hàng", "hải sản", "khách sạn", "homestay", "cafe", "quán ăn", "chỗ ở", "đường đi", "gần đây", "ăn gì", "đâu ngon", "recommend")
_PLACE_KEYWORDS_EN = ("restaurant", "hotel", "cafe", "seafood", "nearby", "directions", "accommodation", "where to eat")
_CULTURAL_KEYWORDS_VI = ("làng chài", "lịch sử", "văn hóa", "di tích", "du lịch", "thú vị", "đặc sản", "gì vui", "có gì")
_CULTURAL_KEYWORDS_EN = ("history", "culture", "fishing village", "travel", "attraction", "ham ninh")


def _classify_query(query_lower: str) -> str:
    """Classify query as 'place', 'cultural', or 'no_evidence'."""
    # Gibberish detection
    if any(g in query_lower for g in ("xyzabc", "qwerty")):
        return "no_evidence"
    # Short query
    if len(query_lower.strip()) < 3:
        return "short"
    # Place detection
    if any(k in query_lower for k in _PLACE_KEYWORDS_VI + _PLACE_KEYWORDS_EN):
        return "place"
    # Cultural detection
    if any(k in query_lower for k in _CULTURAL_KEYWORDS_VI + _CULTURAL_KEYWORDS_EN):
        return "cultural"
    # Default for medium-length queries
    if len(query_lower.strip()) >= 3:
        return "cultural"
    return "short"


def _smart_llm_response(*args, **kwargs) -> MagicMock:
    """Return context-aware mock LLM responses based on query content and language.

    Returns tool_calls for place queries so the AgentService routes them
    to the place recommendation path. Returns direct answers for cultural
    and no-evidence queries.
    """
    messages = kwargs.get("messages", args[1] if len(args) > 1 else [])
    query = ""
    language = "vi"
    for m in messages:
        if m.get("role") == "user":
            query = m.get("content", "").lower()
        if m.get("role") == "system" and ("100% in english" in m.get("content", "").lower() or "tiếng anh" in m.get("content", "").lower()):
            language = "en"

    qtype = _classify_query(query)

    if qtype == "place":
        # Return tool call so AgentService routes to place recommendation
        return _make_tool_call_completion("search_places", json.dumps({"query": query}))
    elif qtype == "no_evidence":
        if language == "en":
            return _make_mock_completion(
                "I'm sorry, but I do not have sufficient information to answer that question."
            )
        return _make_mock_completion(
            "Xin lỗi, mình hiện chưa có thông tin cụ thể về khoản này."
        )
    elif qtype == "cultural":
        if language == "en":
            return _make_mock_completion(
                "Based on the available information, Ham Ninh is a well-known fishing village in Phu Quoc."
            )
        return _make_mock_completion(
            "Theo thông tin hiện có, làng chài Hàm Ninh là một điểm đến nổi tiếng tại Phú Quốc, Kiên Giang."
        )
    elif qtype == "short":
        return _make_mock_completion("unknown")
    else:
        return _make_mock_completion(
            "Theo thông tin hiện có, Hàm Ninh là một làng chài tại Phú Quốc."
        )


_mock_openai = None  # module-level so tests can reference it


@pytest.fixture(scope="function", autouse=True)
def _mock_openai_client():
    """Patch openai.AsyncOpenAI so app startup gets a mock, not a real client.

    Also patch _real_client in agent_service to bypass the MagicMock detection
    (which would otherwise force the deterministic fallback path).

    The mock is smart enough to:
    - Return tool_calls=[search_places] on the FIRST call for place queries,
      triggering the AgentService's place recommendation path
    - Return direct answers for cultural and no-evidence queries
    """
    global _mock_openai
    _mock_openai = MagicMock()
    call_state = {"count": 0}  # mutable counter for this test

    def _side_effect(*args, **kwargs):
        call_state["count"] += 1

        messages = kwargs.get("messages", args[1] if len(args) > 1 else [])
        query = ""
        language = "vi"
        has_tool_result = False
        for m in messages:
            if m.get("role") == "user":
                query = m.get("content", "").lower()
            if m.get("role") == "system":
                sys_content = m.get("content", "").lower()
                if "preferred language: english" in sys_content:
                    language = "en"
            if m.get("role") == "tool":
                has_tool_result = True

        # Extract actual user query (last user message)
        user_msgs = [m for m in messages if m.get("role") == "user"]
        if user_msgs:
            query = user_msgs[-1].get("content", "").lower()

        qtype = _classify_query(query)

        # Second call after tool execution — return language-appropriate answer
        if has_tool_result:
            if language == "en":
                return _make_mock_completion(
                    "Based on the available information, Ham Ninh is a well-known fishing village in Phu Quoc."
                )
            return _make_mock_completion(
                "Theo thông tin hiện có, làng chài Hàm Ninh là một điểm đến nổi tiếng tại Phú Quốc, Kiên Giang."
            )

        if qtype == "place":
            # Return tool call so AgentService routes to place recommendation
            return _make_tool_call_completion("search_places", json.dumps({"query": query}))
        elif qtype == "cultural":
            # Return tool call for knowledge retrieval so intent is set to cultural_query
            return _make_tool_call_completion("search_knowledge", json.dumps({"query": query}))
        elif qtype == "no_evidence":
            if language == "en":
                return _make_mock_completion(
                    "I'm sorry, but I do not have sufficient information to answer that question."
                )
            return _make_mock_completion(
                "Xin lỗi, mình hiện chưa có thông tin cụ thể về khoản này."
            )
        elif qtype == "cultural":
            if language == "en":
                return _make_mock_completion(
                    "Based on the available information, Ham Ninh is a well-known fishing village in Phu Quoc."
                )
            return _make_mock_completion(
                "Theo thông tin hiện có, làng chài Hàm Ninh là một điểm đến nổi tiếng tại Phú Quốc, Kiên Giang."
            )
        elif qtype == "short":
            return _make_mock_completion("unknown")
        else:
            return _make_mock_completion(
                "Theo thông tin hiện có, Hàm Ninh là một làng chài tại Phú Quốc."
            )

    _mock_openai.chat.completions.create = AsyncMock(side_effect=_side_effect)

    def _fake_real_client(llm_service):
        """Bypass MagicMock detection only for our specific mock client."""
        if llm_service is None:
            return None
        client = getattr(llm_service, "_client", None)
        if client is _mock_openai:
            return client  # Our specific mock — bypass detection
        # Fall through to original logic for other mocks
        if client is None or type(client).__module__.startswith("unittest.mock"):
            return None
        return client

    with patch("openai.AsyncOpenAI", return_value=_mock_openai):
        with patch("agents.graph.agent_service._real_client", side_effect=_fake_real_client):
            yield


def _resolve_corpus_path() -> str:
    """Resolve the tourism_documents.jsonl path from either backend/ or project root."""
    p = Path("data/tourism_documents.jsonl")
    if not p.exists():
        p = Path(__file__).resolve().parent.parent.parent / "data" / "tourism_documents.jsonl"
    return str(p)


@pytest.fixture(scope="session")
def loaded_chunks():
    """Load and cache the full tourism corpus for the test session."""
    return load_corpus(_resolve_corpus_path())


@pytest.fixture(scope="session")
def sample_queries():
    """Known Hàm Ninh tourism queries for retrieval testing."""
    return [
        "làng chài Hàm Ninh",
        "Hàm Ninh hải sản",
        "chợ đêm Hàm Ninh",
    ]


@pytest.fixture(scope="session")
def retriever(loaded_chunks):
    """Provide a ready Retriever instance over the full corpus."""
    return Retriever(loaded_chunks)


@pytest.fixture(scope="session")
def qdrant_service():
    """QdrantService pointed at the test Qdrant instance."""
    return QdrantService(url=os.environ.get("QDRANT_URL", "http://localhost:46333"))


@pytest.fixture(scope="session")
def embedding_service():
    """EmbeddingService — only usable in integration tests with a real API key."""
    return EmbeddingService()
