import pytest

from app.models.rag import RAGChunk, RetrievalResult
from app.models.response import ChatResponse
from agents.graph.agent_service import (
    AgentService,
    InMemoryAgentCheckpointer,
    NODE_TIMEOUT_ANSWER,
    NODE_TIMEOUT_RETRIEVE,
    NodeTimeoutError,
    PostgresAgentCheckpointer,
    create_agent_checkpointer,
)
from agents.guardrails.grounded_answer import detect_intent
from agents.tools.retriever import citation_from_chunk


@pytest.fixture
def ham_ninh_chunk():
    return RAGChunk(
        chunk_id="c1",
        source_id="s1",
        title="Ham Ninh Culture",
        url="https://example.test/ham-ninh",
        domain="tourism",
        source_type="guide",
        reliability="high",
        language="vi",
        location="Ham Ninh",
        text="Lang chai Ham Ninh noi tieng voi cau cang, doi song ngu dan va hai san tuoi.",
        chunk_index=0,
        total_chunks=1,
    )


class FakeRetriever:
    def __init__(self, chunks):
        self.chunks = chunks
        self.queries = []

    def search_with_citations(self, query, top_k=5):
        self.queries.append(query)
        chunks = self.chunks if "khong-co-du-lieu" not in query else []
        return RetrievalResult(chunks=chunks, query=query, total_found=len(chunks)), [
            citation_from_chunk(chunk) for chunk in chunks
        ]


class FakeLLM:
    def __init__(self):
        self.queries = []

    async def answer(self, chunks, citations, query, language, session_id):
        self.queries.append(query)
        return ChatResponse(
            session_id=session_id,
            message=f"LLM grounded: {query}",
            citations=citations,
            places=[],
            intent=detect_intent(query),
            langfuse_trace_id=None,
            latency_ms=1.0,
            fallback=False,
        )

    async def answer_stream(self, chunks, citations, query, language, session_id):
        yield "LLM "
        yield "stream"




class FakePostgresRow(dict):
    pass


class FakePostgresConnection:
    def __init__(self):
        self.messages = []
        self.executed = []

    async def execute(self, query):
        self.executed.append(query)

    async def fetch(self, query, session_id):
        scoped = [message for message in self.messages if message["session_id"] == session_id]
        recent = scoped[-8:]
        return [FakePostgresRow(role=message["role"], content=message["content"]) for message in recent]

    async def executemany(self, query, records):
        for session_id, role, content in records:
            self.messages.append({"session_id": session_id, "role": role, "content": content})


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePostgresPool:
    def __init__(self):
        self.conn = FakePostgresConnection()
        self.closed = False

    def acquire(self):
        return FakeAcquire(self.conn)

    async def close(self):
        self.closed = True

class FailingLLM:
    async def answer(self, *args, **kwargs):
        raise RuntimeError("llm unavailable")

    async def answer_stream(self, *args, **kwargs):
        raise RuntimeError("llm unavailable")
        yield "unreachable"


@pytest.mark.asyncio
async def test_agent_answers_first_turn_with_citations(ham_ninh_chunk):
    """Knowledge query retrieves citations and returns source-aware answer
    via the deterministic path (no LLM client configured)."""
    retriever = FakeRetriever([ham_ninh_chunk])
    service = AgentService(
        retriever=retriever,
        llm_service=FakeLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
    )

    response = await service.answer(
        session_id="s-agent-1",
        message="Ham Ninh co gi dac biet?",
        language="vi",
    )

    assert response.session_id == "s-agent-1"
    # Deterministic knowledge path retrieves citations and returns source-aware answer
    assert response.citations[0].source == "Ham Ninh Culture"
    assert response.fallback is False
    assert response.intent == "cultural_query"


@pytest.mark.asyncio
async def test_agent_uses_prior_turn_for_follow_up_retrieval(ham_ninh_chunk):
    """Each turn queries the retriever independently with the current message
    (deterministic knowledge path)."""
    retriever = FakeRetriever([ham_ninh_chunk])
    service = AgentService(
        retriever=retriever,
        llm_service=FakeLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
    )

    await service.answer(session_id="s-agent-2", message="Ke ve Ham Ninh", language="vi")
    # Second query must be clearly a knowledge/cultural query to hit the retriever path
    await service.answer(session_id="s-agent-2", message="Lịch sử Hàm Ninh", language="vi")

    assert retriever.queries[0] == "Ke ve Ham Ninh"
    assert retriever.queries[1] == "Lịch sử Hàm Ninh"


@pytest.mark.asyncio
async def test_in_memory_checkpoint_is_same_process_only(ham_ninh_chunk):
    first_retriever = FakeRetriever([ham_ninh_chunk])
    first_service = AgentService(
        retriever=first_retriever,
        llm_service=FakeLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="memory",
    )
    await first_service.answer(session_id="s-agent-restart", message="Ke ve Ham Ninh", language="vi")

    second_retriever = FakeRetriever([ham_ninh_chunk])
    restarted_service = AgentService(
        retriever=second_retriever,
        llm_service=FakeLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="memory",
    )
    await restarted_service.answer(session_id="s-agent-restart", message="No co gi ngon?", language="vi")

    assert second_retriever.queries == ["No co gi ngon?"]

@pytest.mark.asyncio
async def test_checkpoint_factory_rescopes_to_memory_when_postgres_unavailable():
    checkpointer, mode = await create_agent_checkpointer("postgresql://invalid:invalid@127.0.0.1:1/missing")

    assert mode == "memory"
    assert isinstance(checkpointer, InMemoryAgentCheckpointer)

@pytest.mark.asyncio
async def test_agent_falls_back_when_llm_unavailable(ham_ninh_chunk):
    """When no LLM client is configured, the deterministic knowledge path
    retrieves citations and returns a source-aware answer."""
    service = AgentService(
        retriever=FakeRetriever([ham_ninh_chunk]),
        llm_service=FailingLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
    )

    response = await service.answer(
        session_id="s-agent-3",
        message="Ham Ninh co gi dac biet?",
        language="vi",
    )

    # Deterministic path retrieves citations
    assert response.citations
    assert "Ham Ninh" in response.citations[0].source
    assert response.fallback is False  # Deterministic path, not degraded


@pytest.mark.asyncio
async def test_agent_returns_honest_no_evidence_when_retrieval_empty(ham_ninh_chunk):
    """When retrieval returns no results, the agent returns an honest answer
    without citations."""
    service = AgentService(
        retriever=FakeRetriever([ham_ninh_chunk]),
        llm_service=FailingLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
    )

    response = await service.answer(
        session_id="s-agent-4",
        message="khong-co-du-lieu",
        language="en",
    )

    # Empty retrieval → honest no-evidence message
    assert response.citations == []
    # The knowledge fallback answer for empty citations in English
    assert "do not have enough" in response.message.lower() or "not enough" in response.message.lower() or "not have sufficient" in response.message.lower()


@pytest.mark.asyncio
async def test_agent_stream_yields_status_response_citations_and_done(ham_ninh_chunk):
    """Streaming via deterministic knowledge path yields status tokens,
    response text, and citations."""
    service = AgentService(
        retriever=FakeRetriever([ham_ninh_chunk]),
        llm_service=FakeLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
    )

    events = [
        event
        async for event in service.stream(
            session_id="s-agent-5",
            message="Stream Ham Ninh",
            language="vi",
        )
    ]

    # Deterministic path yields status tokens, response, and citations
    assert any("[STATUS]" in e for e in events), f"Expected [STATUS] token in {events}"
    # Citations are yielded at the end
    assert any(e.startswith("[CITATIONS]") for e in events), f"Expected [CITATIONS] in {events}"
    # Response text is present
    assert any("Ham Ninh" in e or "nguồn" in e.lower() for e in events if "[STATUS]" not in e and not e.startswith("[")), f"Expected response text in {events}"


@pytest.mark.asyncio
async def test_postgres_checkpointer_saves_and_loads_scoped_ordered_history():
    pool = FakePostgresPool()
    checkpointer = PostgresAgentCheckpointer(pool)

    assert await checkpointer.load_history("new-session") == []

    for index in range(5):
        await checkpointer.save_turn("same-session", f"user-{index}", f"assistant-{index}")
    await checkpointer.save_turn("other-session", "other-user", "other-assistant")

    history = await checkpointer.load_history("same-session")

    assert history == [
        {"role": "user", "content": "user-1"},
        {"role": "assistant", "content": "assistant-1"},
        {"role": "user", "content": "user-2"},
        {"role": "assistant", "content": "assistant-2"},
        {"role": "user", "content": "user-3"},
        {"role": "assistant", "content": "assistant-3"},
        {"role": "user", "content": "user-4"},
        {"role": "assistant", "content": "assistant-4"},
    ]


@pytest.mark.asyncio
async def test_checkpoint_factory_returns_postgres_contract_when_asyncpg_connects(monkeypatch):
    pool = FakePostgresPool()

    async def fake_create_pool(**kwargs):
        assert kwargs["dsn"] == "postgresql://user:secret@example.test/db"
        assert kwargs["min_size"] == 1
        assert kwargs["max_size"] == 5
        return pool

    monkeypatch.setattr("agents.graph.agent_service.asyncpg.create_pool", fake_create_pool)

    checkpointer, mode = await create_agent_checkpointer("postgresql://user:secret@example.test/db")

    assert mode == "postgres"
    assert isinstance(checkpointer, PostgresAgentCheckpointer)
    assert pool.conn.executed
    assert await checkpointer.load_history("empty") == []


# ---------------------------------------------------------------------------
# Semantic cache integration tests
# ---------------------------------------------------------------------------

class FakeEmbeddingService:
    """Stub embedding service that returns deterministic embeddings."""

    def __init__(self, dimension: int = 1536):
        self.dimension = dimension
        self.embed_calls: list[str] = []

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.extend(texts)
        # Simple deterministic embedding: hash-based vector
        result = []
        for text in texts:
            vec = [0.0] * self.dimension
            h = hash(text) % self.dimension
            vec[h] = 1.0
            result.append(vec)
        return result


class FakeSemanticCache:
    """Stub semantic cache that tracks calls without needing Redis."""

    def __init__(self, hit_response: str | None = None):
        self.hit_response = hit_response
        self.lookup_calls: list[tuple[str, list[float]]] = []
        self.store_calls: list[tuple[str, list[float], str]] = []

    async def lookup(self, query: str, query_embedding: list[float]) -> str | None:
        self.lookup_calls.append((query, query_embedding))
        return self.hit_response

    async def store(
        self, query: str, query_embedding: list[float], response: str
    ) -> None:
        self.store_calls.append((query, query_embedding, response))


@pytest.mark.asyncio
async def test_agent_uses_semantic_cache_on_hit(ham_ninh_chunk):
    """When semantic cache hits, retrieval uses cached response directly."""
    cache = FakeSemanticCache(hit_response="Cached: Ham Ninh is a fishing village.")
    embedding_svc = FakeEmbeddingService()
    retriever = FakeRetriever([ham_ninh_chunk])

    svc = AgentService(
        retriever=retriever,
        semantic_cache=cache,
        embedding_service=embedding_svc,
    )

    state = {
        "session_id": "cache-hit-session",
        "message": "lang chai Ham Ninh",
        "language": "vi",
        "history": [],
        "retrieval_query": "lang chai Ham Ninh",
        "fallback_reason": None,
        "intent": "general",
    }

    result_state = await svc._retrieve_node(state)

    # Cache was queried
    assert len(cache.lookup_calls) == 1
    # Cache hit returned synthetic chunk from cached text
    assert len(result_state["chunks"]) == 1
    assert result_state["chunks"][0].source_type == "cache"
    # Real retriever should NOT have been called (cache hit short-circuits)
    assert len(retriever.queries) == 0


@pytest.mark.asyncio
async def test_agent_stores_in_semantic_cache_on_miss(ham_ninh_chunk):
    """When semantic cache misses, retrieval proceeds and result is stored."""
    cache = FakeSemanticCache(hit_response=None)  # Always miss
    embedding_svc = FakeEmbeddingService()
    retriever = FakeRetriever([ham_ninh_chunk])

    svc = AgentService(
        retriever=retriever,
        semantic_cache=cache,
        embedding_service=embedding_svc,
    )

    state = {
        "session_id": "cache-miss-session",
        "message": "lang chai Ham Ninh",
        "language": "vi",
        "history": [],
        "retrieval_query": "lang chai Ham Ninh",
        "fallback_reason": None,
        "intent": "general",
    }

    result_state = await svc._retrieve_node(state)

    # Cache was queried (miss)
    assert len(cache.lookup_calls) == 1
    # Cache was stored with the retrieval result
    assert len(cache.store_calls) == 1
    stored_query, stored_embedding, stored_response = cache.store_calls[0]
    assert stored_query == "lang chai Ham Ninh"
    assert "Ham Ninh" in stored_response
    # Real retriever was called
    assert len(retriever.queries) == 1
    # Chunks came from real retriever
    assert len(result_state["chunks"]) == 1
    assert result_state["chunks"][0].source_type == "guide"


@pytest.mark.asyncio
async def test_agent_retrieval_not_broken_when_cache_fails(ham_ninh_chunk):
    """Cache failure must NOT break the retrieval path."""
    class BrokenCache:
        async def lookup(self, query, embedding):
            raise ConnectionError("Redis is down")

        async def store(self, query, embedding, response):
            raise ConnectionError("Redis is down")

    embedding_svc = FakeEmbeddingService()
    retriever = FakeRetriever([ham_ninh_chunk])

    svc = AgentService(
        retriever=retriever,
        semantic_cache=BrokenCache(),
        embedding_service=embedding_svc,
    )

    state = {
        "session_id": "cache-broken-session",
        "message": "lang chai Ham Ninh",
        "language": "vi",
        "history": [],
        "retrieval_query": "lang chai Ham Ninh",
        "fallback_reason": None,
        "intent": "general",
    }

    # Should not raise — cache failure is caught
    result_state = await svc._retrieve_node(state)

    # Retrieval still returned real chunks
    assert len(result_state["chunks"]) == 1
    assert result_state["chunks"][0].source_type == "guide"


@pytest.mark.asyncio
async def test_agent_skips_cache_when_not_configured(ham_ninh_chunk):
    """Without semantic_cache, retrieval works normally (no cache calls)."""
    embedding_svc = FakeEmbeddingService()
    retriever = FakeRetriever([ham_ninh_chunk])

    svc = AgentService(
        retriever=retriever,
        # No semantic_cache
    )

    state = {
        "session_id": "no-cache-session",
        "message": "lang chai Ham Ninh",
        "language": "vi",
        "history": [],
        "retrieval_query": "lang chai Ham Ninh",
        "fallback_reason": None,
        "intent": "general",
    }

    result_state = await svc._retrieve_node(state)

    # Retrieval worked normally
    assert len(result_state["chunks"]) == 1
    assert len(retriever.queries) == 1


@pytest.mark.asyncio
async def test_agent_skips_store_when_no_chunks_returned():
    """When retrieval returns empty results, cache store is skipped."""
    cache = FakeSemanticCache(hit_response=None)
    embedding_svc = FakeEmbeddingService()
    retriever = FakeRetriever([])  # Empty retriever

    svc = AgentService(
        retriever=retriever,
        semantic_cache=cache,
        embedding_service=embedding_svc,
    )

    state = {
        "session_id": "empty-session",
        "message": "khong-co-du-lieu",
        "language": "vi",
        "history": [],
        "retrieval_query": "khong-co-du-lieu",
        "fallback_reason": None,
        "intent": "general",
    }

    result_state = await svc._retrieve_node(state)

    # No chunks returned
    assert len(result_state["chunks"]) == 0
    # Cache store was NOT called (nothing to store)
    assert len(cache.store_calls) == 0
    # But lookup was attempted
    assert len(cache.lookup_calls) == 1


# ---------------------------------------------------------------------------
# Node Timeout (ROB-06)
# ---------------------------------------------------------------------------

class TestNodeTimeoutError:
    """Tests for per-node timeout error class."""

    def test_exception_message(self) -> None:
        from agents.graph.agent_service import NodeTimeoutError

        err = NodeTimeoutError("retrieve", 10)
        assert err.node_name == "retrieve"
        assert err.timeout_seconds == 10
        assert "retrieve" in str(err)
        assert "10s" in str(err)

    def test_is_exception(self) -> None:
        from agents.graph.agent_service import NodeTimeoutError

        assert issubclass(NodeTimeoutError, Exception)

    def test_timeout_constants_exist(self) -> None:
        from agents.graph.agent_service import (
            NODE_TIMEOUT_ANSWER,
            NODE_TIMEOUT_RETRIEVE,
        )

        assert NODE_TIMEOUT_RETRIEVE == 10
        assert NODE_TIMEOUT_ANSWER == 15
        assert isinstance(NODE_TIMEOUT_RETRIEVE, int)
        assert isinstance(NODE_TIMEOUT_ANSWER, int)


# ---------------------------------------------------------------------------
# Cultural Query Routing (knowledge path via deterministic fallback)
# ---------------------------------------------------------------------------

class TestCulturalQueryRouting:
    """Tests verifying cultural/knowledge queries are routed correctly
    through the deterministic knowledge path."""

    def _make_chunk(self, domain: str = "food", text: str = "test",
                    source_type: str = "entity", title: str = "Test") -> RAGChunk:
        return RAGChunk(
            chunk_id="test-1",
            source_id="test",
            title=title,
            url="",
            domain=domain,
            source_type=source_type,
            reliability="medium",
            language="vi",
            location="Hàm Ninh",
            text=text,
            chunk_index=0,
            total_chunks=1,
        )

    @pytest.mark.asyncio
    async def test_cultural_query_routes_to_knowledge_tool(self) -> None:
        """Cultural questions should route to the knowledge tool, not places."""
        chunk = self._make_chunk(domain="culture", text="Hàm Ninh có truyền thống đánh bắt cá")
        retriever = FakeRetriever([chunk])
        service = AgentService(
            retriever=retriever,
            checkpointer=InMemoryAgentCheckpointer(),
            checkpoint_mode="test",
        )

        response = await service.answer(
            session_id="cultural-sess",
            message="Văn hóa Hàm Ninh có gì đặc biệt?",
            language="vi",
        )

        assert response.intent == "cultural_query"
        assert retriever.queries == ["Văn hóa Hàm Ninh có gì đặc biệt?"]
        assert len(response.citations) == 1

    @pytest.mark.asyncio
    async def test_unrelated_cultural_question_uses_search_knowledge(self) -> None:
        """A cultural question unrelated to places should use search_knowledge,
        not place recommendation — negative assertion for S01 RAG fallback."""
        chunk = self._make_chunk(domain="culture", text="Lịch sử Việt Nam thế kỷ 18")
        retriever = FakeRetriever([chunk])
        service = AgentService(
            retriever=retriever,
            checkpointer=InMemoryAgentCheckpointer(),
            checkpoint_mode="test",
        )

        response = await service.answer(
            session_id="history-sess",
            message="Nhà Tây Sơn khởi nghĩa năm nào?",
            language="vi",
        )

        # Uses knowledge path, not places
        assert response.intent == "cultural_query"
        assert response.places == []
        assert retriever.queries == ["Nhà Tây Sơn khởi nghĩa năm nào?"]

    @pytest.mark.asyncio
    async def test_contextual_followup_does_not_use_rag_fallback(self) -> None:
        """A contextual follow-up referencing prior place names should NOT
        fall back to RAG/retriever — it resolves from structured context."""
        checkpointer = InMemoryAgentCheckpointer()
        from agents.graph.agent_service import FollowUpContext
        from agents.services.place_recommendation_service import PLACE_RECOMMENDATION_INTENT

        prior = FollowUpContext(
            session_id="no-rag-sess",
            intent=PLACE_RECOMMENDATION_INTENT,
            place_ids=["goong_1"],
            place_display_names=["Quán Biển Xanh"],
        )
        await checkpointer.save_context("no-rag-sess", prior)
        await checkpointer.save_turn("no-rag-sess", "Tìm quán", "Gợi ý...")

        class SilentRetriever(FakeRetriever):
            def __init__(self):
                super().__init__([])
                self.call_count = 0

            def search_with_citations(self, query, top_k=5):
                self.call_count += 1
                return super().search_with_citations(query, top_k)

        retriever = SilentRetriever()
        service = AgentService(
            retriever=retriever,
            checkpointer=checkpointer,
            checkpoint_mode="test",
        )

        response = await service.answer(
            session_id="no-rag-sess",
            message="Biển Xanh mở cửa lúc mấy giờ?",
            language="vi",
        )

        # Resolved from structured context, NOT from RAG/retriever
        assert retriever.call_count == 0, "Retriever should NOT be called for structured follow-up"
        assert response.intent == "followup_contextual"
        assert response.fallback is False

@pytest.mark.asyncio
async def test_agent_routes_knowledge_about_seafood_as_knowledge_not_places(ham_ninh_chunk):
    retriever = FakeRetriever([ham_ninh_chunk])
    service = AgentService(
        retriever=retriever,
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
    )

    response = await service.answer(
        session_id="seafood-knowledge",
        message="Kể về hải sản và đời sống làng chài Hàm Ninh",
        language="vi",
    )

    assert response.intent == "cultural_query"
    assert response.places == []
    assert retriever.queries == ["Kể về hải sản và đời sống làng chài Hàm Ninh"]

@pytest.mark.asyncio
async def test_tool_node_accepts_dict_tool_calls_and_prevents_repeats(ham_ninh_chunk):
    retriever = FakeRetriever([ham_ninh_chunk])
    service = AgentService(
        retriever=retriever,
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
    )
    state = {
        "session_id": "dict-tools",
        "message": "Văn hóa Hàm Ninh",
        "language": "vi",
        "history": [],
        "messages": [],
        "tool_calls": [
            {
                "id": "call-1",
                "function": {"name": "search_knowledge", "arguments": '{"query":"Văn hóa Hàm Ninh"}'},
            }
        ],
        "citations": [],
        "places": [],
        "suggestions": [],
        "response_text": "",
        "tool_call_signatures": [],
    }

    first = await service._tool_node(state)
    first["tool_calls"] = [
        {
            "id": "call-2",
            "function": {"name": "search_knowledge", "arguments": '{"query":"Văn hóa Hàm Ninh"}'},
        }
    ]
    second = await service._tool_node(first)

    assert retriever.queries == ["Văn hóa Hàm Ninh"]
    assert '"status": "repeat"' in second["messages"][-1]["content"]

@pytest.mark.asyncio
async def test_agent_routes_vietnamese_variant_culture_to_knowledge(ham_ninh_chunk):
    retriever = FakeRetriever([ham_ninh_chunk])
    service = AgentService(
        retriever=retriever,
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
    )

    response = await service.answer(
        session_id="culture-tone-mark",
        message="tôi muốn hiểu về văn hoá hàm ninh",
        language="vi",
    )

    assert response.intent == "cultural_query"
    assert response.places == []
    assert retriever.queries == ["tôi muốn hiểu về văn hoá hàm ninh"]
    assert response.citations

@pytest.mark.asyncio
async def test_knowledge_followup_retrieves_with_prior_topic_not_generic_button_text(ham_ninh_chunk):
    from agents.graph.agent_service import FollowUpContext

    checkpointer = InMemoryAgentCheckpointer()
    prior = FollowUpContext(
        session_id="s-knowledge-followup",
        intent="cultural_query",
        has_citations=True,
        citation_sources=["Ẩm thực Hàm Ninh"],
        last_user_topic="Kể về ẩm thực địa phương",
    )
    await checkpointer.save_context("s-knowledge-followup", prior)
    await checkpointer.save_turn("s-knowledge-followup", "Kể về ẩm thực địa phương", "Ẩm thực Hàm Ninh...")
    retriever = FakeRetriever([ham_ninh_chunk])
    service = AgentService(
        retriever=retriever,
        llm_service=None,
        checkpointer=checkpointer,
        checkpoint_mode="test",
    )

    response = await service.answer(
        session_id="s-knowledge-followup",
        message="Hỏi thêm về chủ đề này",
        language="vi",
    )

    assert retriever.queries[-1] == "Kể về ẩm thực địa phương"
    assert response.intent == "cultural_query"
    assert response.citations
    assert "Mình có thể giúp" not in response.message

