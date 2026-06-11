"""State and structured contracts for the Ham Ninh LangGraph."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from app.models.response import Citation
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

NODE_TIMEOUT_GUARDRAILS = 6
NODE_TIMEOUT_ROUTER = 8
NODE_TIMEOUT_LLM = 25
NODE_TIMEOUT_TOOL = 30






AgentRunStatus = Literal[
    "planning",
    "gathering",
    "waiting_for_user_input",
    "verifying",
    "completed",
    "failed-recoverable",
    "failed-terminal",
]

IntentLabel = Literal[
    "cultural_query",
    "food_culture",
    "restaurant_search",
    "navigation",
    "conversational",
    "unknown",
]


class AgentState(TypedDict, total=False):
    # Persisted conversation identity and memory.
    session_id: str
    message: str
    language: str
    history: list[dict[str, str]]
    messages: Annotated[list[Any], add_messages]

    # Replayable execution state.
    run_status: AgentRunStatus
    current_step: str | None
    retry_count: int
    error_code: str | None
    tool_calls: list[Any]
    tool_receipts: list[dict[str, Any]]
    pending_input: dict[str, Any] | None
    reasoning_log: str | None

    # Turn-scoped routing and output.
    intent: str | None
    intent_confidence: float | None
    is_followup: bool
    needs_location: bool
    response_text: str
    citations: list[Citation]
    places: list[Any]
    suggestions: list[str]
    guardrail_flags: dict[str, Any]
    blocked: bool

    # Current request preferences.
    user_location: dict[str, float] | None
    budget_filter: str | None
    accessibility_required: bool

    # Persisted grounded place context for comparative follow-ups.
    last_places: list[Any]
    last_place_query: str | None
    last_place_included_type: str | None
    last_place_accessibility_required: bool
    last_place_user_location: dict[str, float] | None

    # Retrieval artifacts.
    knowledge_chunks: list[Any]


class RouterOutput(BaseModel):
    """Structured intent classifier output."""

    intent: IntentLabel
    confidence: float = Field(ge=0.0, le=1.0)
    is_followup: bool
    needs_location: bool


SYSTEM_PROMPT = """\
Bạn là Trợ lý Hàm Ninh cho du lịch bền vững.

- Chỉ trả lời trực tiếp cho hội thoại đơn giản hoặc câu hỏi có thể giải quyết từ lịch sử.
- Câu hỏi văn hóa, lịch sử và ẩm thực phải dựa trên dữ liệu truy xuất và trích dẫn.
- Tìm địa điểm, tuyến đường và câu hỏi phù hợp cho gia đình phải dựa trên dữ liệu nhà cung cấp.
- Không bịa giá, khả năng tiếp cận, an toàn, giờ mở cửa, địa hình hoặc điều kiện trực tiếp.
- Khi dữ liệu yếu hoặc thiếu, nói rõ phần chưa xác nhận và cách kiểm tra.
- Chỉ yêu cầu vị trí trình duyệt cho yêu cầu phụ thuộc vị trí hiện tại như "gần tôi".
- Trả lời bằng ngôn ngữ của người dùng.
- Cuối câu trả lời, thêm đúng ba gợi ý ngắn theo mẫu:
  [SUGGESTIONS] Gợi ý 1 | Gợi ý 2 | Gợi ý 3
"""
