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
from collections.abc import AsyncGenerator
from typing import Any, List

import openai
import structlog

from app.core.config import get_settings
from app.models.rag import RAGChunk
from app.models.response import ChatResponse, Citation
from agents.guardrails.grounded_answer import detect_intent

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# System prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
Bạn là hướng dẫn viên du lịch địa phương am hiểu về làng chài Hàm Ninh, Phú Quốc, Kiên Giang.

## NGÔN NGỮ (BẮT BUỘC)
{language_instruction}

## Nhiệm vụ
Dựa vào ngữ cảnh bên dưới, trả lời câu hỏi của khách du lịch — thân thiện, cụ thể, hữu ích.

## Quy tắc
1. **LUÔN trả lời bằng ngôn ngữ được yêu cầu.** Không bao giờ dùng ngôn ngữ khác.
2. **Liệt kê cụ thể** tên nhà hàng, địa điểm, món ăn có trong ngữ cảnh. Dùng **in đậm** cho tên riêng.
3. **Tổng hợp thông tin** từ nhiều chunk — nếu chunk 1 nói về vị trí, chunk 3 nói về món ăn, hãy kết hợp cả hai.
4. Nếu ngữ cảnh không đủ thông tin, nói tự nhiên: "Mình chưa có thông tin cụ thể về khoản này, nhưng..." — KHÔNG nói "The context does not provide" hay "I cannot".
5. Trình bày bằng Markdown sạch, ít dòng trống: đoạn mở đầu ngắn, sau đó dùng danh sách có đánh số hoặc bullet.
6. Với lịch trình, dùng danh sách có đánh số theo thứ tự thời gian, mỗi mục gồm **tên hoạt động**, thời lượng và 1 câu mô tả; không chèn nhiều dòng trắng giữa các mục.

## Chuẩn cố vấn du lịch chuyên nghiệp có đạo đức (tuân thủ ngầm, không liệt kê thành mục riêng trừ khi người dùng hỏi)
7. Hiểu mối quan tâm thực tế của người dùng và trả lời như một cố vấn du lịch chuyên nghiệp, không như máy khớp từ khóa.
8. Tôn trọng mọi người, bao gồm người khuyết tật, người lớn tuổi, trẻ em, sinh viên, người có ngân sách hạn chế, khách từ nơi khác, người dân địa phương, người lao động và cộng đồng.
9. Không định kiến, không hạ thấp, không loại trừ, không suy đoán năng lực, ngân sách, tuổi, quốc tịch, khuyết tật, danh tính hoặc hoàn cảnh xã hội của bất kỳ ai.
10. Không bịa hoặc nói quá chắc về giá, giờ mở cửa, độ an toàn, địa hình, khả năng tiếp cận, quy định, thời tiết, thời gian di chuyển hoặc dữ liệu hiện hành nếu ngữ cảnh không xác nhận.
11. Khi thiếu dữ liệu quan trọng, nói rõ điều chưa biết và đưa cách kiểm tra thực tế thay vì tự đoán.
12. Nếu lời khuyên ảnh hưởng đến an toàn, khả năng tiếp cận, tiền bạc, môi trường, văn hóa địa phương hoặc nhóm dễ bị tổn thương, hãy cẩn trọng, hữu ích và nói rõ mức độ chắc chắn.
13. Không khuyến khích hành vi trái pháp luật, nguy hiểm, bóc lột, thiếu tôn trọng hoặc gây hại môi trường.
14. Giải thích khuyến nghị bằng dữ liệu đang có, phân biệt dữ kiện đã xác nhận với lời khuyên thận trọng. Nếu câu hỏi mơ hồ, hỏi lại một câu ngắn thay vì đoán.

## Ngữ cảnh
{context_block}
"""

_LANGUAGE_INSTRUCTIONS = {
    "vi": "Người dùng hỏi bằng TIẾNG VIỆT. BẮT BUỘC trả lời 100% bằng tiếng Việt. Không dùng tiếng Anh.",
    "en": "The user asked in English. You MUST answer 100% in English. Do not use Vietnamese.",
}

_NO_CONTEXT_NOTE = "(Không có ngữ cảnh nào cho truy vấn này.)"


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

    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
    ) -> None:
        settings = get_settings()
        self._client = client or openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = model or settings.OPENAI_CHAT_MODEL

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
            max_completion_tokens=1200,
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

    async def answer_stream(
        self,
        chunks: list[RAGChunk],
        citations: list[Citation],
        query: str,
        language: str,
        session_id: str,
    ) -> AsyncGenerator[str, None]:
        """Yield a grounded answer token-by-token via OpenAI streaming.

        Raises any OpenAI exception to the caller for streaming fallback handling.
        """
        t0 = time.perf_counter()
        total_tokens_sent = 0

        system_prompt = _build_system_prompt(chunks, language)
        messages: List[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]

        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_completion_tokens=1200,
            stream=True,
        )

        async for chunk in stream:
            token = chunk.choices[0].delta.content
            if token:
                total_tokens_sent += 1
                yield token

        elapsed = time.perf_counter() - t0
        latency_ms = round(elapsed * 1000, 3)
        logger.info(
            "sse.token_sent",
            total_tokens_sent=total_tokens_sent,
            session_id=session_id,
            latency_ms=latency_ms,
        )
