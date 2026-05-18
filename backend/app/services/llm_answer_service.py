"""LLM-powered grounded answer service using OpenAI gpt-4o-mini.

Replaces deterministic answer composition with a real chat completion call.
Retrieved chunks are injected as numbered context into the system prompt,
preventing the model from fabricating facts not present in the corpus.

Fallback ownership lives in the router (D020): this service raises on any
OpenAI error so the router can catch, log llm.fallback, and delegate to
GroundedAnswerService.answer_from_chunks().
"""

from __future__ import annotations

import time
from typing import List

import openai
import structlog

from app.core.config import get_settings
from app.models.rag import RAGChunk
from app.models.response import ChatResponse, Citation
from app.services.grounded_answer import detect_intent

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# System prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
You are a helpful tourism assistant for Hàm Ninh, a fishing village on Phú Quốc Island, Vietnam.

Your task is to answer the user's question using ONLY the context chunks provided below.
Do NOT fabricate any facts, names, dates, places, prices, or details that are not explicitly stated in the context.
If the context does not contain enough information to answer the question, say so honestly — do not guess or invent details.

{language_instruction}

Context:
{context_block}
"""

_LANGUAGE_INSTRUCTIONS = {
    "vi": "Answer in Vietnamese.",
    "en": "Answer in English.",
}

_NO_CONTEXT_NOTE = "(No context chunks are available for this query.)"


def _build_system_prompt(chunks: list[RAGChunk], language: str) -> str:
    """Build the grounding system prompt from retrieved chunks.

    Args:
        chunks: Retrieved RAGChunk objects to use as grounding context.
        language: Response language code ('vi' or 'en').

    Returns:
        Fully-formed system prompt string.
    """
    lang_instruction = _LANGUAGE_INSTRUCTIONS.get(language.lower(), _LANGUAGE_INSTRUCTIONS["en"])

    if not chunks:
        context_block = _NO_CONTEXT_NOTE
    else:
        lines: list[str] = []
        for i, chunk in enumerate(chunks, start=1):
            lines.append(f"[{i}] {chunk.title}: {chunk.text}")
        context_block = "\n".join(lines)

    return _SYSTEM_PROMPT_TEMPLATE.format(
        language_instruction=lang_instruction,
        context_block=context_block,
    )


# ---------------------------------------------------------------------------
# LLMAnswerService
# ---------------------------------------------------------------------------

class LLMAnswerService:
    """Async service that answers queries via OpenAI gpt-4o-mini with grounding.

    The caller (router) is responsible for fallback handling: if ``answer()``
    raises, the router catches the exception, logs ``llm.fallback``, and
    delegates to ``GroundedAnswerService.answer_from_chunks()``.

    Usage::

        svc = LLMAnswerService()
        response = await svc.answer(
            chunks=chunks,
            citations=citations,
            query="Hàm Ninh có gì đặc biệt?",
            language="vi",
            session_id="sess-abc-123",
        )
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model: str = settings.OPENAI_CHAT_MODEL

    async def answer(
        self,
        chunks: list[RAGChunk],
        citations: list[Citation],
        query: str,
        language: str,
        session_id: str,
    ) -> ChatResponse:
        """Generate a grounded answer via OpenAI chat completion.

        Injects retrieved chunks as numbered context into the system prompt.
        Raises any OpenAI exception to the caller for fallback handling.

        Args:
            chunks: Pre-retrieved RAGChunk objects used as grounding context.
            citations: Corresponding Citation objects for the chunks.
            query: Original user query.
            language: Preferred response language ('vi' or 'en').
            session_id: Opaque session identifier for correlation.

        Returns:
            ChatResponse with fallback=False and the LLM-generated message.

        Raises:
            openai.OpenAIError: On any API failure (auth, rate-limit, timeout, etc.).
        """
        t0 = time.perf_counter()

        system_prompt = _build_system_prompt(chunks, language)
        messages: List[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]

        completion = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.2,
            max_tokens=512,
        )

        elapsed = time.perf_counter() - t0
        latency_ms = round(elapsed * 1000, 3)

        answer_text: str = completion.choices[0].message.content or ""
        tokens_used: int = completion.usage.total_tokens if completion.usage else 0

        logger.info(
            "llm.answer_complete",
            query=query,
            language=language,
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            session_id=session_id,
        )

        return ChatResponse(
            session_id=session_id,
            message=answer_text,
            citations=citations,
            places=[],
            intent=detect_intent(query),
            langfuse_trace_id=None,
            latency_ms=latency_ms,
            fallback=False,
        )

    async def answer_stream(self, *args, **kwargs):  # noqa: ANN002, ANN003
        """Streaming variant — to be implemented in S04.

        Will yield token chunks via an async generator using
        ``stream=True`` on the chat completions call.
        """
        raise NotImplementedError(
            "answer_stream() will be implemented in S04 (streaming responses). "
            "Use answer() for non-streaming responses."
        )
