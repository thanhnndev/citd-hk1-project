"""Shared state and tool contracts for the LangGraph chat agent."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from app.models.response import ChatResponse, Citation

try:
    from langgraph.graph import END, START, StateGraph
    from langgraph.checkpoint.memory import MemorySaver
except Exception:  # pragma: no cover - optional runtime dependency
    END = "__end__"
    START = "__start__"
    StateGraph = None
    MemorySaver = None

NODE_TIMEOUT_LLM = 20
NODE_TIMEOUT_TOOL = 15
NODE_TIMEOUT_RETRIEVE = 10
NODE_TIMEOUT_ANSWER = 15


class NodeTimeoutError(Exception):
    """Raised when a graph node exceeds its per-node timeout."""

    def __init__(self, node_name: str, timeout_seconds: int) -> None:
        self.node_name = node_name
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Node '{node_name}' timed out after {timeout_seconds}s")


ToolName = Literal["search_knowledge", "search_places"]
FollowUpDecision = Literal[
    "structured_context",
    "history_context",
    "clarification_needed",
    "insufficient_context",
]


class AgentState(TypedDict, total=False):
    session_id: str
    message: str
    language: str
    history: list[dict[str, str]]
    messages: list[dict[str, Any]]
    tool_calls: list[Any]
    citations: list[Citation]
    places: list[Any]
    suggestions: list[str]
    reasoning_log: str | None
    intent: str | None
    response_text: str
    response: ChatResponse
    langfuse_trace_id: str | None
    prior_context: Any | None
    followup_decision: FollowUpDecision | None
    context_source: str | None
    tool_call_signatures: list[str]


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": (
                "Use only for factual Ham Ninh culture/history/travel knowledge that needs evidence. "
                "Do not use for greetings, help/capability questions, follow-ups that can be answered from history, "
                "or place/hotel/restaurant discovery."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_places",
            "description": (
                "Use for restaurants, hotels, homestays, cafes, seafood, nearby places, directions, maps, routes, "
                "or local recommendations around Ham Ninh. "
                "Optionally accepts budget, accessibility, and user_location preferences."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "budget": {
                        "type": "string",
                        "enum": ["free", "inexpensive", "moderate", "expensive", "very_expensive"],
                        "description": "Optional budget preference. Maps to price level filtering.",
                    },
                    "accessibility": {
                        "type": "boolean",
                        "description": "Optional: when true, prefer wheelchair-accessible venues.",
                    },
                    "user_location": {
                        "type": "object",
                        "properties": {
                            "lat": {"type": "number"},
                            "lng": {"type": "number"},
                        },
                        "description": "Optional user GPS coordinates for proximity scoring.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]

SYSTEM_PROMPT = """\
Bạn là Trợ lý Hàm Ninh cho du lịch bền vững.

Follow this exact tool policy:
- Answer directly for greetings, thanks, capability/help questions, and follow-ups answerable from conversation history.
- Ask one clarification question when the request is underspecified.
- Call search_places for restaurants, hotels, homestays, cafes, seafood, nearby places, directions, routes, maps, or recommendations.
- Call search_knowledge only for factual Ham Ninh knowledge requiring evidence: culture, history, fishing life, local food background, travel notes.
- Never call search_knowledge as a fallback for place requests or short follow-ups.
- Cite only facts from search_knowledge results. Do not cite place results as document sources.
- If a tool is unavailable or returns no useful data, say that honestly and ask a useful follow-up.
- Reply in the user's language.
- At the end of your final response (when you are not calling any tools), write exactly three short and context-specific suggestion chips for the user's next turn in this format: [SUGGESTIONS] Suggestion 1 | Suggestion 2 | Suggestion 3. Do not include this tag or suggestions if you are proposing tool calls.
"""
