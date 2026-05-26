"""Output guardrails — grounding verification for LLM responses.

Wraps every assistant reply before it reaches the client, checking that
claims made in the message are supported by the attached source material.

Emits structured log events:
- ``guardrail.output_verified`` — grounding check completed (pass)
- ``guardrail.output_flagged`` — grounding check failed (flagged)
- ``guardrail.degraded`` — guardrails running in degraded mode
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Literal

import structlog

from agents.guardrails.input_guardrails import GuardrailResult

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# overlap_ratio >= HIGH_THRESHOLD → pass
HIGH_THRESHOLD: float = 0.15
# LOW_THRESHOLD <= overlap_ratio < HIGH_THRESHOLD → flagged (low confidence)
LOW_THRESHOLD: float = 0.05

# ---------------------------------------------------------------------------
# Known no-evidence / honest-uncertainty messages
# ---------------------------------------------------------------------------

_NO_EVIDENCE_PATTERNS: list[re.Pattern[str]] = [
    # English
    re.compile(r"\b(i['']m|i am)\s+(not\s+)?(sure|certain|positive)\b", re.IGNORECASE),
    re.compile(r"\bi\s+don['']t\s+(have|know)\b", re.IGNORECASE),
    re.compile(r"\bi\s+couldn['']t\s+find\b", re.IGNORECASE),
    re.compile(r"\bno\s+(information|results|data|evidence)\s+(found|available)\b", re.IGNORECASE),
    re.compile(r"\bi\s+(do\s+)?not\s+have\s+(enough\s+)?information\b", re.IGNORECASE),
    re.compile(r"\bunfortunately\b.*\b(found|available|able)\b", re.IGNORECASE),
    re.compile(r"\bnot\s+enough\s+data\b", re.IGNORECASE),
    re.compile(r"\bi\s+do\s+not\s+have\s+access\b", re.IGNORECASE),
    # Vietnamese
    re.compile(r"tôi\s+(không\s+)?(biết|rõ|chắc)", re.IGNORECASE),
    re.compile(r"không\s+(có\s+)?thông\s+tin", re.IGNORECASE),
    re.compile(r"không\s+tìm\s+thấy", re.IGNORECASE),
    re.compile(r"không\s+đủ\s+thông\s+tin", re.IGNORECASE),
    re.compile(r"xin\s+lỗi.*không\s+có", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Tokenization helpers
# ---------------------------------------------------------------------------

# Stop words to filter out (common function words in EN + VI)
_STOP_WORDS: set[str] = {
    # English stop words
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "both",
    "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "and", "but", "or", "because", "if", "while", "about", "that", "this",
    "these", "those", "it", "its", "i", "me", "my", "we", "our", "you",
    "your", "he", "him", "his", "she", "her", "they", "them", "their",
    "what", "which", "who", "whom", "also", "much", "many",
    # Vietnamese stop words
    "là", "và", "hoặc", "trong", "trên", "dưới", "của", "cho", "với",
    "để", "bởi", "vì", "khi", "nếu", "thì", "mà", "nhưng", "còn",
    "có", "không", "đã", "đang", "sẽ", "rất", "hơn", "từ", "đến",
    "các", "những", "một", "này", "đó", "này", "được", "bị", "tại",
    "về", "nơi", "như", "ra", "lại", "nên", "ra", "vào", "lên",
    "xuống", "qua", "sau", "trước", "gì", "ai", "đâu", "nào",
}

# Punctuation / whitespace splitter
_TOKEN_RE = re.compile(r"[a-zA-Z0-9À-ỹà-ỹ]+", re.UNICODE)


def _extract_key_tokens(text: str) -> set[str]:
    """Extract content-bearing tokens from text.

    Filters out stop words, single-character tokens, and pure punctuation.
    Keeps numbers, proper nouns (capitalized), and content words.
    """
    tokens = _TOKEN_RE.findall(text.lower())
    return {
        t for t in tokens
        if t not in _STOP_WORDS
        and len(t) > 1
    }


def _compute_overlap_ratio(
    message_tokens: set[str],
    source_tokens: set[str],
) -> float:
    """Compute the fraction of message key tokens found in source material."""
    if not message_tokens:
        return 0.0
    shared = message_tokens & source_tokens
    return len(shared) / len(message_tokens)


# ---------------------------------------------------------------------------
# Citation text extraction
# ---------------------------------------------------------------------------

def _extract_citation_text(citations: list | None) -> str:
    """Combine all citation text into a single string.

    Accepts both Citation objects (with .snippet / .source) and
    RAGChunk objects (with .text / .title).
    """
    if not citations:
        return ""

    parts: list[str] = []
    for citation in citations:
        # Try RAGChunk attributes first
        text = getattr(citation, "text", None)
        if text and text.strip():
            parts.append(text)

        title = getattr(citation, "title", None)
        if title and title.strip():
            parts.append(title)

        # Try Citation attributes
        snippet = getattr(citation, "snippet", None)
        if snippet and snippet.strip():
            parts.append(snippet)

        source = getattr(citation, "source", None)
        if source and source.strip():
            parts.append(source)

        url = getattr(citation, "url", None)
        if url:
            parts.append(url)

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Honest-uncertainty detection
# ---------------------------------------------------------------------------

def _is_no_evidence_message(message: str) -> bool:
    """Check if the message is a known no-evidence / uncertainty expression."""
    for pattern in _NO_EVIDENCE_PATTERNS:
        if pattern.search(message):
            return True
    return False


# ---------------------------------------------------------------------------
# Public guardrail function
# ---------------------------------------------------------------------------

def verify_grounding(
    message: str,
    citations: list | None = None,
) -> GuardrailResult:
    """Verify that an LLM response is grounded in retrieved source material.

    Extracts key content tokens from the message and measures overlap
    with the combined text of all citations.

    Args:
        message: The LLM-generated response text.
        citations: List of Citation objects or RAGChunk objects providing
            source material. Can be None or empty.

    Returns:
        GuardrailResult with:
        - verdict="pass" if sufficiently grounded or correctly ungrounded
        - verdict="flagged" if claims appear ungrounded
    """
    query_hash = hashlib.sha256(
        message.encode("utf-8")
    ).hexdigest()[:16]

    # Edge case: empty or whitespace-only message
    if not message or not message.strip():
        logger.info(
            "guardrail.output_verified",
            verdict="pass",
            reason="empty_message",
            query_hash=query_hash,
            overlap_ratio=0.0,
        )
        return GuardrailResult(
            verdict="pass",
            reason="empty_message",
        )

    message_tokens = _extract_key_tokens(message)

    # No citations provided
    if not citations:
        if _is_no_evidence_message(message):
            # Correctly ungrounded — the model is being honest
            logger.info(
                "guardrail.output_verified",
                verdict="pass",
                reason="honest_uncertainty",
                query_hash=query_hash,
                overlap_ratio=0.0,
            )
            return GuardrailResult(
                verdict="pass",
                reason="honest_uncertainty",
                details="Model correctly expressed uncertainty without sources",
            )
        else:
            # Making claims without any source material
            logger.warning(
                "guardrail.output_flagged",
                verdict="flagged",
                reason="no_source_material",
                query_hash=query_hash,
                key_token_count=len(message_tokens),
                severity="high",
            )
            return GuardrailResult(
                verdict="flagged",
                reason="no_source_material",
                details="Confident response with no citations",
                severity="high",
            )

    # Citations exist — compute grounding overlap
    citation_text = _extract_citation_text(citations)
    source_tokens = _extract_key_tokens(citation_text)

    if not source_tokens:
        # All citations are empty
        if _is_no_evidence_message(message):
            logger.info(
                "guardrail.output_verified",
                verdict="pass",
                reason="honest_uncertainty",
                query_hash=query_hash,
                overlap_ratio=0.0,
            )
            return GuardrailResult(verdict="pass", reason="honest_uncertainty")
        else:
            logger.warning(
                "guardrail.output_flagged",
                verdict="flagged",
                reason="empty_citations",
                query_hash=query_hash,
                severity="medium",
            )
            return GuardrailResult(
                verdict="flagged",
                reason="empty_citations",
                details="All citations contain no extractable content",
                severity="medium",
            )

    overlap_ratio = _compute_overlap_ratio(message_tokens, source_tokens)

    # Count ungrounded claims (tokens NOT found in source)
    ungrounded_tokens = message_tokens - source_tokens
    ungrounded_claim_count = len(ungrounded_tokens)

    # Threshold-based verdict
    if overlap_ratio >= HIGH_THRESHOLD:
        logger.info(
            "guardrail.output_verified",
            verdict="pass",
            reason="grounded",
            query_hash=query_hash,
            overlap_ratio=round(overlap_ratio, 4),
            ungrounded_token_count=ungrounded_claim_count,
        )
        return GuardrailResult(
            verdict="pass",
            reason="grounded",
            details=f"Overlap ratio: {overlap_ratio:.4f}",
        )
    elif overlap_ratio >= LOW_THRESHOLD:
        logger.warning(
            "guardrail.output_flagged",
            verdict="flagged",
            reason="low_confidence",
            query_hash=query_hash,
            overlap_ratio=round(overlap_ratio, 4),
            ungrounded_token_count=ungrounded_claim_count,
            severity="low",
        )
        return GuardrailResult(
            verdict="flagged",
            reason="low_confidence",
            details=f"Low overlap ratio: {overlap_ratio:.4f}",
            severity="low",
        )
    else:
        logger.warning(
            "guardrail.output_flagged",
            verdict="flagged",
            reason="ungrounded",
            query_hash=query_hash,
            overlap_ratio=round(overlap_ratio, 4),
            ungrounded_token_count=ungrounded_claim_count,
            severity="high",
        )
        return GuardrailResult(
            verdict="flagged",
            reason="ungrounded",
            details=f"Very low overlap ratio: {overlap_ratio:.4f}",
            severity="high",
        )
