"""Shared state and tool contracts for the LangGraph chat agent."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from app.models.response import ChatResponse, Citation

try:
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover - optional runtime dependency
    BaseModel = None  # type: ignore[assignment,misc]
    Field = None  # type: ignore[assignment]

try:
    from langgraph.graph import END, START, StateGraph
    from langgraph.graph.message import add_messages
    from langgraph.checkpoint.memory import MemorySaver
except Exception:  # pragma: no cover - optional runtime dependency
    END = "__end__"
    START = "__start__"
    StateGraph = None
    MemorySaver = None

    def add_messages(left: list[Any], right: list[Any]) -> list[Any]:
        return [*(left or []), *(right or [])]

NODE_TIMEOUT_LLM = 20
NODE_TIMEOUT_TOOL = 15
NODE_TIMEOUT_RETRIEVE = 10
NODE_TIMEOUT_ANSWER = 15

# Per-node timeouts for new v4.2.0 graph nodes (Section 14.2)
NODE_TIMEOUT_GUARDRAILS = 3
NODE_TIMEOUT_INTENT_ROUTER = 5
NODE_TIMEOUT_GRADE = 5
NODE_TIMEOUT_REWRITE = 8
NODE_TIMEOUT_SEMANTIC_FALLBACK = 3


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
    messages: Annotated[list[dict[str, Any]], add_messages]
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
    resolved_query: str | None
    tool_call_signatures: list[str]
    knowledge_chunks: list[Any]
    knowledge_response_ready: bool
    # --- v4.2.0 agent intelligence fields ---
    # Routing
    intent_confidence: float | None
    routing_tier: Literal["strict", "soft", "fallback"] | None
    needs_location: bool
    next_node: str | None  # Routing hint from supervisor to conditional edge (T02)
    # Guardrails
    guardrail_flags: dict[str, Any]
    # Self-corrective RAG
    grade_score: float | None
    grade_label: str | None
    rewrite_count: int
    rewritten_query: str | None
    # Session memory boundaries
    history_included: bool
    # User location opt-in (v4.2.0)
    location_consent: bool
    sort_by_nearest: bool
    user_location: dict[str, float] | None
    # Graph flow control
    blocked: bool
    # User preference filters (v4.3.0)
    budget_filter: str | None
    accessibility_required: bool


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

Follow the LangGraph tool-calling pattern: reason over the full conversation, then either answer directly or call the single best tool. Do not behave like a keyword router.

Intent judgement rules:
- Answer directly only for greetings, thanks, capability/help questions, simple acknowledgements, and follow-ups clearly answerable from conversation history.
- Ask one concise clarification question when a request is genuinely underspecified and a tool call would need missing information, e.g. bare "đường" without origin/destination.
- Use search_knowledge when the user wants to understand Hàm Ninh: culture/văn hóa/văn hoá, history/lịch sử, fishing life, local food background, travel notes, origin stories, factual explanations, or a terse follow-up topic after a knowledge answer such as "hải sản".
- Use search_places when the user wants concrete venue discovery or navigation: restaurants, seafood places, hotels, homestays, cafes, nearby places, directions, routes, maps, or local recommendations.
- For ambiguous short user turns, use conversation context first. If the previous answer was about local food and the user says "HẢI SẢN", treat it as a knowledge follow-up unless they ask for a venue. If the previous answer listed venues and the user asks "đường", ask which place/origin if not clear.
- Mixed requests are allowed: choose the tool that best serves the main intent first; call a second tool only if the user explicitly asks for that second output.
- Do not use brittle keyword decisions. Same words can imply different intents depending on phrasing and history: "kể về hải sản" is knowledge; "tìm quán hải sản" is places; "đường" alone is clarification; "chỉ đường đến chợ Hàm Ninh" is places/navigation.

Grounding and response rules:
- Cite only facts from search_knowledge results. Do not cite place results as document sources.
- If search_knowledge returns weak or empty evidence, say what is missing instead of inventing facts.
- If search_places is unavailable or returns no useful data, say that honestly and ask a practical follow-up.
- Reply in the user's language.
- At the end of your final response (when you are not calling any tools), write exactly three short and context-specific suggestion chips for the user's next turn in this format: [SUGGESTIONS] Suggestion 1 | Suggestion 2 | Suggestion 3. Do not include this tag or suggestions if you are proposing tool calls.
"""


# ---------------------------------------------------------------------------
# Structured output schemas for v4.2.0 agent intelligence (Section 14.3)
# ---------------------------------------------------------------------------

IntentLabel = Literal[
    "cultural_query",
    "food_culture",
    "restaurant_search",
    "navigation",
    "conversational",
    "unknown",
]

if BaseModel is not None:

    class RouterOutput(BaseModel):
        """Structured intent classifier output for confidence-ladder routing.

        Produced by OpenAI structured output (``response_format=RouterOutput``).
        The confidence float drives the routing tier:
          ≥ 0.75  → strict (direct to RAG or Maps agent)
          0.45–0.75 → soft (supervisor with tool-calling)
          < 0.45  → fallback (semantic-router embedding similarity)
        """

        intent: IntentLabel = Field(
            description="Classified intent category"
        )
        confidence: float = Field(
            ge=0.0,
            le=1.0,
            description="Classifier confidence in [0, 1]",
        )
        is_followup: bool = Field(
            description="True when the message references prior conversation context"
        )
        needs_location: bool = Field(
            description="True when the query requires user GPS (e.g. nearby, directions)"
        )

    class GradeDocuments(BaseModel):
        """Document relevance grading output for self-corrective RAG.

        Produced by OpenAI structured output for the grade_documents node.
        binary_score is 'yes' when the retrieved chunk is relevant to the
        user question, 'no' otherwise.
        """

        binary_score: Literal["yes", "no"] = Field(
            description="Relevance score: 'yes' if relevant, 'no' if not relevant"
        )

    class RewriteQuery(BaseModel):
        """Query rewrite output for self-corrective RAG.

        Produced by OpenAI structured output for the rewrite_query node.
        The rewritten_query preserves the original intent but improves
        specificity and retrieval likelihood.
        """

        rewritten_query: str = Field(
            description="Improved query preserving original intent and language"
        )
        reasoning: str = Field(
            default="",
            description="Brief reasoning for the rewrite (for observability)",
        )

else:  # pragma: no cover - pydantic unavailable
    RouterOutput = None  # type: ignore[assignment,misc]
    GradeDocuments = None  # type: ignore[assignment,misc]
    RewriteQuery = None  # type: ignore[assignment,misc]
