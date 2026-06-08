"""Input guardrails — prompt injection blocking and topic rejection.

Pure-Python module with no FastAPI dependency.  Wraps every user message
before it reaches the agent orchestration layer.

Emits structured log events:
- ``guardrail.input_blocked`` — prompt injection detected
- ``guardrail.topic_rejected`` — off-topic query rejected
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

import structlog

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
# Topic allowlist / blocklist
# ---------------------------------------------------------------------------

# Out-of-scope locations (not Ham Ninh / Phu Quoc)
_OUT_OF_SCOPE_LOCATIONS: list[tuple[str, str]] = [
    ("hanoi", r"\b(hà nội|hanoi|ha noi)\b"),
    ("saigon", r"\b(sài gòn|saigon|sai gon|hồ chí minh|ho chi minh|hcm)\b"),
    ("danang", r"\b(đà nẵng|danang|da nang)\b"),
    ("hue", r"\b(huế|hue)\b"),
    ("nhatrang", r"\b(nha trang|nhatrang)\b"),
    ("dalat", r"\b(đà lạt|dalat|da lat)\b"),
    ("hoian", r"\b(hội an|hoian|hoi an)\b"),
    ("hanoi_airport", r"\b(nội bài|noi bai)\b"),
    ("saigon_airport", r"\b(tân sơn nhất|tan son nhat)\b"),
]

_OUT_OF_SCOPE_LOCATIONS_RE: list[tuple[str, re.Pattern[str]]] = [
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in _OUT_OF_SCOPE_LOCATIONS
]

_OFF_TOPIC_ALLOWLIST_VI: set[str] = {
    # Greetings
    "xin chào", "chào", "hello", "hi", "hey",
    # Tourism-adjacent (only valid if in scope)
    "khách sạn", "hotel", "resort",
    "vận chuyển", "transport", "xe", "taxi", "bus",
    "biển", "beach", "ăn uống", "food", "restaurant",
    "du lịch", "travel", "tourism", "tham quan",
    "địa điểm", "điểm đến", "attraction",
    "mua sắm", "shopping", "giá cả", "price",
}

_OFF_TOPIC_ALLOWLIST_EN: set[str] = {
    "hello", "hi", "hey", "good morning", "good afternoon", "good evening",
    "how are you", "greetings",
    "hotel", "resort", "transport", "taxi", "bus",
    "beach", "food", "restaurant", "travel", "tourism",
    "attraction", "shopping", "price", "cost", "ticket",
    "direction", "map", "guide", "itinerary",
}

_OFF_TOPIC_BLOCKLIST: list[tuple[str, str]] = [
    ("code_write", r"(write\s+code|python\s+script|javascript|function|algorithm|program|coding)"),
    ("code_help", r"(debug|fix\s+(this\s+)?code|implement\s+(a\s+)?(class|function|method))"),
    ("math_homework", r"(solve\s+(this\s+)?(equation|math|calculus|integral|derivative)|prove\s+that)"),
    ("explicit_content", r"(porn|sex|nude|nsfw|xxx|18\+)"),
    ("politics_vote", r"(vote|election|president|political\s+party|campaign|đảng\s+phái|bầu\s+cử)"),
    ("medical_advice", r"(diagnose|prescribe|treatment\s+plan|medical\s+advice|triage)"),
]

_OFF_TOPIC_BLOCKLIST_RE: list[tuple[str, re.Pattern[str]]] = [
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in _OFF_TOPIC_BLOCKLIST
]


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


def reject_off_topic(message: str) -> GuardrailResult:
    """Reject clearly off-topic queries that fall outside Ham Ninh tourism scope.

    Uses scope-based approach:
    1. Check location scope — reject if mentions out-of-scope locations (Hanoi, Saigon, etc.)
    2. Check blocklist — reject programming, explicit content, politics, etc.
    3. Check allowlist — accept tourism-adjacent keywords if in scope
    4. Conservative pass-through for borderline cases

    Returns:
        GuardrailResult with verdict="blocked" for out-of-scope or blocklisted topics,
        verdict="pass" otherwise.
    """
    if not message or not message.strip():
        return GuardrailResult(verdict="pass")

    cleaned = _strip_zero_width(message)
    normalized = _normalize(cleaned)
    query_hash = _hash_query(message)

    # Check location scope first — reject queries about other locations
    for label, pattern in _OUT_OF_SCOPE_LOCATIONS_RE:
        if pattern.search(normalized):
            logger.warning(
                "guardrail.topic_rejected",
                verdict="blocked",
                reason="out_of_scope_location",
                location=label,
                query_hash=query_hash,
                severity="medium",
            )
            return GuardrailResult(
                verdict="blocked",
                reason="off_topic",
                details=f"out_of_scope:{label}",
                severity="medium",
            )

    # Check blocklist — these are hard rejects
    for label, pattern in _OFF_TOPIC_BLOCKLIST_RE:
        if pattern.search(normalized):
            logger.warning(
                "guardrail.topic_rejected",
                verdict="blocked",
                reason="off_topic",
                pattern_matched=label,
                query_hash=query_hash,
                severity="medium",
            )
            return GuardrailResult(
                verdict="blocked",
                reason="off_topic",
                details=label,
                severity="medium",
            )

    # Check if message hits the allowlist — if so, it's on-topic enough
    for keyword in _OFF_TOPIC_ALLOWLIST_VI | _OFF_TOPIC_ALLOWLIST_EN:
        if keyword.lower() in normalized:
            return GuardrailResult(verdict="pass")

    # No keywords matched either list — conservative pass-through
    return GuardrailResult(verdict="pass")
