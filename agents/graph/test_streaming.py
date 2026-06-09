"""Tests for the LangGraph streaming adapter (T04)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.graph.streaming import (
    StreamingAdapter,
    stream_graph_to_sse,
    emit_token,
    emit_status,
    emit_custom,
)
from agents.graph.state import NodeTimeoutError


class FakeCitation:
    def __init__(self, title: str, url: str):
        self.title = title
        self.url = url
    
    def model_dump(self):
        return {"title": self.title, "url": self.url}


class FakePlace:
    def __init__(self, name: str, lat: float):
        self.name = name
        self.lat = lat
    
    def model_dump(self):
        return {"name": self.name, "lat": self.lat}


@pytest.fixture
def adapter():
    return StreamingAdapter()


@pytest.fixture
def mock_graph():
    graph = MagicMock()
    graph.astream = MagicMock()
    return graph


async def _collect_events(async_gen):
    """Helper to collect all events from an async generator."""
    events = []
    async for event in async_gen:
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_adapter_maps_input_guardrails_blocked(adapter):
    """A blocked request enters the terminal failure state."""
    async def fake_stream():
        yield {
            "type": "updates",
            "data": {
                "input_guardrails": {"guardrail_blocked": True}
            }
        }
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    assert "[STATUS] failed-terminal" in events


@pytest.mark.asyncio
async def test_adapter_maps_input_guardrails_validating(adapter):
    """A valid request enters planning."""
    async def fake_stream():
        yield {
            "type": "updates",
            "data": {
                "input_guardrails": {"guardrail_blocked": False}
            }
        }
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    assert "[STATUS] planning" in events


@pytest.mark.asyncio
async def test_adapter_maps_intent_router(adapter):
    """Internal routing remains represented as user-facing planning."""
    async def fake_stream():
        yield {
            "type": "updates",
            "data": {
                "intent_router": {"intent": "travel", "intent_confidence": 0.85}
            }
        }
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    assert "[STATUS] planning" in events


@pytest.mark.asyncio
async def test_adapter_maps_supervisor(adapter):
    """Internal dispatch remains represented as user-facing planning."""
    async def fake_stream():
        yield {
            "type": "updates",
            "data": {
                "supervisor": {"next_node": "rag_agent"}
            }
        }

    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    assert "[STATUS] planning" in events


@pytest.mark.asyncio
async def test_adapter_maps_conversational_response(adapter):
    """Completed conversational response is marked as a full message, not a token."""
    async def fake_stream():
        yield {
            "type": "updates",
            "data": {
                "conversational": {"response_text": "Xin chào!"}
            }
        }
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    assert "[MESSAGE] Xin chào!" in events
    assert "Xin chào!" not in events


@pytest.mark.asyncio
async def test_adapter_maps_rag_agent(adapter):
    """RAG work is exposed as evidence gathering."""
    async def fake_stream():
        yield {
            "type": "updates",
            "data": {
                "rag_agent": {}
            }
        }
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    assert "[STATUS] gathering:knowledge" in events


@pytest.mark.asyncio
async def test_adapter_maps_maps_agent(adapter):
    """Place lookup is exposed as place gathering."""
    async def fake_stream():
        yield {
            "type": "updates",
            "data": {
                "maps_agent": {}
            }
        }
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    assert "[STATUS] gathering:places" in events


@pytest.mark.asyncio
async def test_adapter_maps_output_guardrails(adapter):
    """Output guardrails node yields [STATUS] verifying."""
    async def fake_stream():
        yield {
            "type": "updates",
            "data": {
                "output_guardrails": {}
            }
        }
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    assert "[STATUS] verifying" in events


@pytest.mark.asyncio
async def test_adapter_handles_custom_token_events(adapter):
    """Custom token events are yielded as raw text."""
    async def fake_stream():
        yield {
            "type": "custom",
            "data": {"type": "token", "content": "Hello"}
        }
        yield {
            "type": "custom",
            "data": {"type": "token", "content": " world"}
        }
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    assert events == ["Hello", " world"]


@pytest.mark.asyncio
async def test_adapter_does_not_repeat_completed_message_after_real_tokens(adapter):
    """Node updates must not replay response_text after custom token deltas."""
    async def fake_stream():
        yield {"type": "custom", "data": {"type": "token", "content": "Xin chào"}}
        yield {
            "type": "updates",
            "data": {"conversational": {"response_text": "Xin chào"}},
        }

    events = await _collect_events(adapter.adapt_stream(fake_stream()))

    assert events.count("Xin chào") == 1
    assert "[MESSAGE] Xin chào" not in events


@pytest.mark.asyncio
async def test_adapter_emits_final_response_as_message_not_token(adapter):
    """Final response_text fallback is a full message marker, not fake token streaming."""
    async def fake_stream():
        yield {
            "type": "updates",
            "data": {
                "output_guardrails": {"response_text": "Completed answer"}
            }
        }

    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    assert "[MESSAGE] Completed answer" in events
    assert "Completed answer" not in events


@pytest.mark.asyncio
async def test_adapter_handles_custom_status_events(adapter):
    """Custom status events are yielded as [STATUS] markers."""
    async def fake_stream():
        yield {
            "type": "custom",
            "data": {"type": "status", "content": "thinking"}
        }
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    assert "[STATUS] thinking" in events


@pytest.mark.asyncio
async def test_adapter_handles_arbitrary_custom_events(adapter):
    """Arbitrary custom events are yielded as [CUSTOM] JSON."""
    async def fake_stream():
        yield {
            "type": "custom",
            "data": {"type": "debug", "level": "info", "message": "test"}
        }
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    assert any(e.startswith("[CUSTOM]") for e in events)
    custom_event = [e for e in events if e.startswith("[CUSTOM]")][0]
    assert "debug" in custom_event


@pytest.mark.asyncio
async def test_adapter_emits_places_marker(adapter):
    """Final state with places yields [PLACES] marker."""
    places = [FakePlace("Phu Quoc", 10.3), FakePlace("Ham Ninh", 10.2)]
    
    async def fake_stream():
        yield {
            "type": "updates",
            "data": {
                "rag_agent": {"places": places}
            }
        }
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    places_events = [e for e in events if e.startswith("[PLACES]")]
    assert len(places_events) == 1
    places_data = json.loads(places_events[0].replace("[PLACES] ", ""))
    assert len(places_data) == 2
    assert places_data[0]["name"] == "Phu Quoc"


@pytest.mark.asyncio
async def test_adapter_emits_citations_marker(adapter):
    """Final state with citations yields [CITATIONS] marker."""
    citations = [FakeCitation("Guide 1", "http://example.com/1")]
    
    async def fake_stream():
        yield {
            "type": "updates",
            "data": {
                "rag_agent": {"citations": citations}
            }
        }
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    citations_events = [e for e in events if e.startswith("[CITATIONS]")]
    assert len(citations_events) == 1
    citations_data = json.loads(citations_events[0].replace("[CITATIONS] ", ""))
    assert len(citations_data) == 1
    assert citations_data[0]["title"] == "Guide 1"


@pytest.mark.asyncio
async def test_adapter_emits_suggestions_marker(adapter):
    """Final state with suggestions yields [SUGGESTIONS] marker."""
    suggestions = ["What else?", "Tell me more"]
    
    async def fake_stream():
        yield {
            "type": "updates",
            "data": {
                "conversational": {"suggestions": suggestions}
            }
        }
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    suggestions_events = [e for e in events if e.startswith("[SUGGESTIONS]")]
    assert len(suggestions_events) == 1
    suggestions_data = json.loads(suggestions_events[0].replace("[SUGGESTIONS] ", ""))
    assert suggestions_data == suggestions


@pytest.mark.asyncio
async def test_adapter_handles_node_timeout_error(adapter):
    """NodeTimeoutError yields [ERROR] with node name."""
    async def fake_stream():
        yield {
            "type": "updates",
            "data": {
                "rag_agent": {}
            }
        }
        raise NodeTimeoutError("rag_agent", 15)
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    error_events = [e for e in events if e.startswith("[ERROR]")]
    assert len(error_events) == 1
    assert "rag_agent" in error_events[0]
    assert "timed out" in error_events[0]


@pytest.mark.asyncio
async def test_adapter_handles_generic_exception(adapter):
    """Generic exceptions yield [ERROR] with error type."""
    async def fake_stream():
        yield {
            "type": "updates",
            "data": {
                "conversational": {"response_text": "Start"}
            }
        }
        raise ValueError("Something went wrong")
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    error_events = [e for e in events if e.startswith("[ERROR]")]
    assert len(error_events) == 1
    assert "ValueError" in error_events[0]


@pytest.mark.asyncio
async def test_adapter_handles_empty_stream(adapter):
    """Empty stream yields no events."""
    async def fake_stream():
        return
        yield  # Make it an async generator
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    assert events == []


@pytest.mark.asyncio
async def test_adapter_ignores_unknown_chunk_types(adapter):
    """Unknown chunk types are silently ignored."""
    async def fake_stream():
        yield {
            "type": "unknown_type",
            "data": {"foo": "bar"}
        }
        yield {
            "type": "updates",
            "data": {
                "conversational": {"response_text": "Hello"}
            }
        }
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    assert "[MESSAGE] Hello" in events
    assert not any("foo" in e for e in events)


@pytest.mark.asyncio
async def test_adapter_handles_dict_places_and_citations(adapter):
    """Places and citations as plain dicts are serialized correctly."""
    async def fake_stream():
        yield {
            "type": "updates",
            "data": {
                "rag_agent": {
                    "places": [{"name": "Beach", "lat": 10.5}],
                    "citations": [{"title": "Source", "url": "http://test.com"}]
                }
            }
        }
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    places_events = [e for e in events if e.startswith("[PLACES]")]
    citations_events = [e for e in events if e.startswith("[CITATIONS]")]
    
    assert len(places_events) == 1
    assert len(citations_events) == 1
    
    places_data = json.loads(places_events[0].replace("[PLACES] ", ""))
    assert places_data[0]["name"] == "Beach"


@pytest.mark.asyncio
async def test_stream_graph_to_sse_convenience_function(mock_graph):
    """stream_graph_to_sse wraps adapter for convenient graph streaming."""
    async def fake_astream(*args, **kwargs):
        yield {
            "type": "updates",
            "data": {
                "conversational": {"response_text": "Test response"}
            }
        }
    
    mock_graph.astream = fake_astream
    
    state = {"session_id": "test", "message": "hello"}
    config = {"configurable": {"thread_id": "test"}}
    
    events = await _collect_events(stream_graph_to_sse(mock_graph, state, config))
    assert "[MESSAGE] Test response" in events


@pytest.mark.asyncio
async def test_stream_graph_to_sse_handles_graph_failure(mock_graph):
    """stream_graph_to_sse yields [ERROR] on graph execution failure."""
    async def failing_astream(*args, **kwargs):
        raise RuntimeError("Graph crashed")
        yield  # Make it an async generator
    
    mock_graph.astream = failing_astream
    
    state = {"session_id": "test", "message": "hello"}
    config = {"configurable": {"thread_id": "test"}}
    
    events = await _collect_events(stream_graph_to_sse(mock_graph, state, config))
    error_events = [e for e in events if e.startswith("[ERROR]")]
    assert len(error_events) == 1
    assert "RuntimeError" in error_events[0]


def test_emit_token_helper():
    """emit_token writes token event to writer."""
    writer = MagicMock()
    emit_token(writer, "Hello")
    writer.assert_called_once_with({"type": "token", "content": "Hello"})


def test_emit_status_helper():
    """emit_status writes status event to writer."""
    writer = MagicMock()
    emit_status(writer, "thinking")
    writer.assert_called_once_with({"type": "status", "content": "thinking"})


def test_emit_custom_helper():
    """emit_custom writes arbitrary custom event to writer."""
    writer = MagicMock()
    data = {"type": "debug", "level": "info"}
    emit_custom(writer, data)
    writer.assert_called_once_with(data)


@pytest.mark.asyncio
async def test_adapter_accumulates_state_across_updates(adapter):
    """Adapter accumulates state updates and emits all markers at end."""
    async def fake_stream():
        yield {
            "type": "updates",
            "data": {
                "intent_router": {"intent": "travel"}
            }
        }
        yield {
            "type": "updates",
            "data": {
                "rag_agent": {
                    "places": [{"name": "Beach"}],
                    "citations": [{"title": "Guide"}]
                }
            }
        }
        yield {
            "type": "updates",
            "data": {
                "conversational": {
                    "response_text": "Here are places",
                    "suggestions": ["More?"]
                }
            }
        }
    
    events = await _collect_events(adapter.adapt_stream(fake_stream()))
    
    # Check status markers
    assert "[STATUS] planning" in events
    assert "[STATUS] gathering:knowledge" in events
    
    # Check completed message (from conversational node)
    assert "[MESSAGE] Here are places" in events
    
    # Check final markers
    assert any(e.startswith("[PLACES]") for e in events)
    assert any(e.startswith("[CITATIONS]") for e in events)
    assert any(e.startswith("[SUGGESTIONS]") for e in events)
