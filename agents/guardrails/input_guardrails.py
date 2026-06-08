"""Input guardrails — prompt injection blocking and topic rejection.

Uses LLM-based classification for scope validation (not hardcoded keywords).
Pure-Python module with no FastAPI dependency.

Emits structured log events:
- ``guardrail.input_blocked`` — prompt injection detected
- ``guardrail.topic_rejected`` — off-topic query rejected
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# GuardrailResult — shared verdict container
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GuardrailResult:
    """Result of a single guardrail evaluation."""

    verdict: Literal["pass", "blocked", "flagged"]
    reason: str = ""
    details: str | None = None
    severity: Literal["high", "medium", "low"] = "low"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_QUERY_HASH_CHARS = 16


def _hash_query(message: str) -> str:
    """Return a short SHA-256 hex digest of the message (no raw text in logs)."""
    return hashlib.sha256(message.encode("utf-8")).hexdigest()[:_QUERY_HASH_CHARS]


def _normalize(message: str) -> str:
    """Apply Unicode NFC normalization and lowercase for pattern matching."""
    return unicodedata.normalize("NFC", message).lower()


def _strip_zero_width(message: str) -> str:
    """Remove zero-width characters that may obscure pattern detection."""
    # U+200B ZWSP, U+200C ZWNJ, U+200D ZWJ, U+FEFF BOM/ZWNBSP, U+2060 WORD JOINER
    return re.sub(r"[\u200b\u200c\u200d\ufeff\u2060]", "", message)


# ---------------------------------------------------------------------------
# Injection blocking patterns
# ---------------------------------------------------------------------------

# English jailbreak / system-override phrases
_INJECTION_PATTERNS_EN: list[tuple[str, str]] = [
    ("jailbreak_dan", r"\bdan\b"),
    ("jailbreak_dan_mode", r"\bdan\s+mode\b"),
    ("ignore_previous", r"ignore\s+(previous|all|my|these)\s+(instructions?|rules?|commands?|prompts?|constraints?)"),
    ("you_are_now", r"\byou\s+are\s+now\b"),
    ("disregard", r"\bdisregard\b"),
    ("system_prompt", r"(system\s+prompt|system\s+message|system\s+instruction)"),
    ("new_instructions", r"new\s+(instructions?|rules?|directives?|orders?)"),
    ("forget_everything", r"\bforget\s+(everything|all|previous|what|your)\b"),
    ("role_escape", r"\b(act|pretend|role-?play|behave)\s+(as|like)\s+(a\s+)?(different|new|another)\b"),
    ("markdown_system", r"```[\s\S]*(system|instruction|directive|rule)[\s\S]*```"),
]

# Vietnamese injection phrases
_INJECTION_PATTERNS_VI: list[tuple[str, str]] = [
    ("vi_ignore", r"b[ỏo] qua (hư[ớơ]ng d[ẫẩ]n|ch[ỉỉ] th[ịị]|quy t[ắă]c)"),
    ("vi_ignore_short", r"l[ờờ] đi"),
    ("vi_system", r"(h[ệệ] th[ốố]ng|l[ệệ]nh h[ệệ] th[ốố]ng)"),
    ("vi_forget", r"quên (h[ếế]t|mọi|tất c[ảả])"),
    ("vi_new_rules", r"quy t[ắă]c m[ớới|moi]"),
    ("vi_pretend", r"(gi[ảả] v[ờờ]|đóng vai) (làm|một)"),
]

# Compile patterns once at import time
_INJECTION_RE: list[tuple[str, re.Pattern[str]]] = [
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in _INJECTION_PATTERNS_EN + _INJECTION_PATTERNS_VI
]

# ---------------------------------------------------------------------------
# LLM-based scope classification (replaces hardcoded keyword matching)
# ---------------------------------------------------------------------------


class ScopeClassification(BaseModel):
    """LLM classification for scope validation.

    Guardrail best practice is to make the model return a calibrated routing
    decision, then only hard-block high-confidence out-of-scope requests.
    """

    decision: Literal["in_scope", "out_of_scope", "uncertain"] = Field(
        description="Scope decision for the user query"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Classifier confidence in the decision",
    )
    category: Literal[
        "ham_ninh_tourism",
        "phu_quoc_tourism",
        "local_food_or_places",
        "directions_or_location",
        "weather_local",
        "weather_other_location",
        "other_location_tourism",
        "unrelated",
        "ambiguous",
    ] = Field(description="Semantic category used for auditability")
    reason: str = Field(
        description="Brief explanation of why the query is in/out of scope"
    )


_SCOPE_PROMPT = """You are a scope validator for the Ham Ninh Tourism Assistant.

Follow guardrail best practice: block only clearly unrelated requests. If the
query is ambiguous but plausibly asks for travel, food, places, directions, or
local recommendations, classify it as in_scope or uncertain so the graph can ask
clarifying questions, request location, or route to tools.

SCOPE:
- Ham Ninh fishing village (làng chài Hàm Ninh)
- Phu Quoc island (đảo Phú Quốc)
- Local attractions, restaurants, seafood places, hotels, culture, history, trip planning
- Directions, maps, distance, or "near me / nearby / gần đây" local recommendations
- Weather in Ham Ninh or Phu Quoc

OUT OF SCOPE:
- Explicit questions about OTHER cities/provinces/countries without relation to Ham Ninh/Phu Quoc
- Weather in OTHER named locations
- General knowledge unrelated to tourism
- Programming, technical questions, politics, etc.

Decision rules:
- Return in_scope for local/deictic tourism requests such as "near me", "nearby", "gần đây", "gần tôi", even if Ham Ninh/Phu Quoc is not named.
- Return uncertain when the query is too short or missing context but could be travel/food/place related.
- Return out_of_scope only when the request is clearly outside the assistant domain.

Examples:
- "Tìm quán hải sản gần đây" → in_scope, local_food_or_places, high confidence
- "Có quán ăn nào gần tôi không?" → in_scope, local_food_or_places, high confidence
- "Thời tiết Hà Nội" → out_of_scope, weather_other_location, high confidence
- "Thời tiết Hàm Ninh" → in_scope, weather_local, high confidence
- "Quán ăn ngon ở Sài Gòn" → out_of_scope, other_location_tourism, high confidence
- "Quán ăn ngon" → uncertain, ambiguous, medium confidence
- "Làng chài Hàm Ninh có gì đặc biệt?" → in_scope, ham_ninh_tourism, high confidence

Validate the user's query and return the structured decision."""


# ---------------------------------------------------------------------------
# Public guardrail functions
# ---------------------------------------------------------------------------

def block_injection(message: str) -> GuardrailResult:
    """Detect prompt injection attacks in a user message.

    Normalises input with Unicode NFC, strips zero-width characters,
    then checks against bilingual injection patterns.

    Returns:
        GuardrailResult with verdict="blocked" if an injection pattern is
        matched, otherwise verdict="pass".
    """
    if not message or not message.strip():
        return GuardrailResult(verdict="pass")

    cleaned = _strip_zero_width(message)
    normalized = _normalize(cleaned)
    query_hash = _hash_query(message)

    for label, pattern in _INJECTION_RE:
        if pattern.search(normalized):
            logger.warning(
                "guardrail.input_blocked",
                verdict="blocked",
                reason="injection_detected",
                pattern_matched=label,
                query_hash=query_hash,
                severity="high",
            )
            return GuardrailResult(
                verdict="blocked",
                reason="injection_detected",
                details=label,
                severity="high",
            )

    return GuardrailResult(verdict="pass")


async def reject_off_topic(
    message: str,
    llm_client: Any | None = None,
    model: str = "gpt-4o-mini",
) -> GuardrailResult:
    """Reject off-topic queries using LLM structured-output scope classification.

    This follows the LangGraph documented pattern for LLM routing/grading:
    define a Pydantic schema, call the model with ``response_format``, then
    route/block from the structured decision. No location or topic keyword
    allowlist is used for scope decisions.
    """
    if not message or not message.strip():
        return GuardrailResult(verdict="pass")

    query_hash = _hash_query(message)

    if llm_client is None:
        logger.warning(
            "guardrail.degraded",
            reason="scope_llm_unavailable",
            query_hash=query_hash,
        )
        return GuardrailResult(verdict="flagged", reason="scope_llm_unavailable")

    try:
        completion = await llm_client.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": _SCOPE_PROMPT},
                {"role": "user", "content": message},
            ],
            response_format=ScopeClassification,
            max_completion_tokens=160,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise ValueError("scope classifier returned no parsed output")

        if parsed.decision == "out_of_scope" and parsed.confidence >= 0.75:
            logger.warning(
                "guardrail.topic_rejected",
                verdict="blocked",
                reason="out_of_scope",
                llm_reason=parsed.reason,
                confidence=parsed.confidence,
                category=parsed.category,
                query_hash=query_hash,
                severity="medium",
            )
            return GuardrailResult(
                verdict="blocked",
                reason="off_topic",
                details=f"out_of_scope:{parsed.category}:{parsed.reason}",
                severity="medium",
            )

        if parsed.decision == "out_of_scope":
            logger.info(
                "guardrail.topic_uncertain_passed",
                reason="low_confidence_out_of_scope",
                llm_reason=parsed.reason,
                confidence=parsed.confidence,
                category=parsed.category,
                query_hash=query_hash,
            )
            return GuardrailResult(verdict="flagged", reason=parsed.reason, details=parsed.category)

        if parsed.decision == "uncertain":
            return GuardrailResult(verdict="flagged", reason=parsed.reason, details=parsed.category)

        return GuardrailResult(verdict="pass", reason=parsed.reason, details=parsed.category)

    except Exception as exc:
        logger.warning(
            "guardrail.llm_classification_failed",
            error_type=type(exc).__name__,
            error=str(exc),
            query_hash=query_hash,
        )
        return GuardrailResult(verdict="flagged", reason="scope_llm_failed", severity="medium")
