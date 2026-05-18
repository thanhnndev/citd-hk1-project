import pytest

from app.models.rag import RAGChunk, RetrievalResult
from app.models.response import ChatResponse
from app.services.agent_service import (
    AgentService,
    InMemoryAgentCheckpointer,
    PostgresAgentCheckpointer,
    create_agent_checkpointer,
)
from app.services.grounded_answer import detect_intent
from app.services.retriever import citation_from_chunk


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
    assert response.message.startswith("LLM grounded:")
    assert response.fallback is False
    assert response.citations[0].source == "Ham Ninh Culture"


@pytest.mark.asyncio
async def test_agent_uses_prior_turn_for_follow_up_retrieval(ham_ninh_chunk):
    retriever = FakeRetriever([ham_ninh_chunk])
    service = AgentService(
        retriever=retriever,
        llm_service=FakeLLM(),
        checkpointer=InMemoryAgentCheckpointer(),
        checkpoint_mode="test",
    )

    await service.answer(session_id="s-agent-2", message="Ke ve Ham Ninh", language="vi")
    await service.answer(session_id="s-agent-2", message="No co gi ngon?", language="vi")

    assert retriever.queries[0] == "Ke ve Ham Ninh"
    assert retriever.queries[1] == "Ke ve Ham Ninh\nNo co gi ngon?"


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

    assert response.fallback is True
    assert response.citations
    assert "Ham Ninh" in response.message


@pytest.mark.asyncio
async def test_agent_returns_honest_no_evidence_when_retrieval_empty(ham_ninh_chunk):
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

    assert response.fallback is True
    assert response.citations == []
    assert "do not have sufficient information" in response.message


@pytest.mark.asyncio
async def test_agent_stream_yields_tokens_citations_and_done(ham_ninh_chunk):
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

    assert events[:2] == ["LLM ", "stream"]
    assert events[-2].startswith("[CITATIONS]")
    assert events[-1] == "[DONE]"


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

    monkeypatch.setattr("app.services.agent_service.asyncpg.create_pool", fake_create_pool)

    checkpointer, mode = await create_agent_checkpointer("postgresql://user:secret@example.test/db")

    assert mode == "postgres"
    assert isinstance(checkpointer, PostgresAgentCheckpointer)
    assert pool.conn.executed
    assert await checkpointer.load_history("empty") == []
