from __future__ import annotations

import hashlib
import inspect
import json
import math
import time
from typing import Any, Literal

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from app.models.rag import RAGChunk
from app.models.response import Citation
from agents.graph.state import AgentState, RouterOutput
from agents.guardrails.input_guardrails import block_injection, reject_off_topic
from agents.guardrails.output_guardrails import verify_grounding
from agents.graph.routing import (_clarify_message, _direct_answer, _extract_suggestions, _fallback_action, _get_default_suggestions, _messages_for_llm)
from agents.tools.retriever import citation_from_chunk
from agents.graph.dependencies import NodeServices, configure_services, get_services
from agents.graph.helpers import *

logger = structlog.get_logger(__name__)
# 6. rag_agent_node (REAL — hybrid retrieval + Cohere rerank + LLM answer)
# ---------------------------------------------------------------------------


async def rag_agent_node(state: AgentState) -> dict[str, Any]:
    """RAG agent node: retrieve, rerank, and generate a grounded answer.

    Pipeline:
        1. Retrieve top-10 chunks via the injected retriever (hybrid or BM25).
        2. Rerank with Cohere cross-encoder (top-5) when available.
        3. Build citations from the reranked chunks.
        4. Generate a grounded answer via LLMAnswerService when available.
        5. Fall back to deterministic text on any LLM or retrieval failure.

    Reads:
        - ``state["message"]``, ``state["rewritten_query"]``,
          ``state["language"]``, ``state["session_id"]``
    Writes:
        - ``knowledge_chunks``, ``citations``, ``response_text``,
          ``knowledge_response_ready``
    """
    t0 = time.perf_counter()
    message = state.get("message", "")
    language = state.get("language", "vi")
    session_id = state.get("session_id", "")

    logger.info(
        "graph.node_enter",
        node="rag_agent",
        session_id=session_id,
    )

    services = get_services()
    retriever = services.retriever
    cohere_reranker = services.cohere_reranker
    llm_answer_service = services.llm_answer_service

    # Check semantic cache first
    query_embedding = None
    if services.semantic_cache is not None and services.embedding_service is not None:
        try:
            embeddings = await services.embedding_service.embed_texts([message])
            query_embedding = embeddings[0] if embeddings else None
            if query_embedding is not None:
                cached = await services.semantic_cache.lookup(message, query_embedding)
                if cached is not None:
                    try:
                        cache_data = json.loads(cached)
                        cached_response = cache_data.get("response_text", "")
                        cached_chunks_data = cache_data.get("knowledge_chunks", [])
                        cached_citations_data = cache_data.get("citations", [])
                        
                        cached_chunks = [RAGChunk.model_validate(c) for c in cached_chunks_data]
                        cached_citations = [Citation.model_validate(c) for c in cached_citations_data]
                    except Exception:
                        # Fallback for old simple cache entries
                        cached_response = cached
                        cached_chunks = [RAGChunk(
                            chunk_id="cache_hit", source_id="semantic_cache", title="Semantic Cache Hit",
                            url="", domain="cache", source_type="cache", reliability="low", language=language,
                            location="", text=cached, chunk_index=0, total_chunks=1,
                        )]
                        cached_citations = [Citation(
                            source="Semantic Cache Hit",
                            url="",
                            snippet=cached[:200]
                        )]
                    
                    elapsed = round((time.perf_counter() - t0) * 1000, 3)
                    logger.info(
                        "graph.node_exit",
                        node="rag_agent",
                        session_id=session_id,
                        mode="semantic_cache_hit",
                        chunk_count=len(cached_chunks),
                        citation_count=len(cached_citations),
                        duration_ms=elapsed,
                    )
                    return {
                        "knowledge_chunks": cached_chunks,
                        "citations": cached_citations,
                        "response_text": cached_response,
                        "run_status": "gathering",
                        "current_step": "knowledge",
                        "tool_receipts": [{
                            "tool": "semantic_cache",
                            "status": "hit",
                            "result_count": len(cached_chunks),
                        }],
                    }
        except Exception as exc:
            logger.warning(
                "rag_agent.semantic_cache_failed",
                error=str(exc),
                session_id=session_id,
            )

    # ------------------------------------------------------------------
    # Step 1: Retrieve top-10 chunks
    # ------------------------------------------------------------------
    chunks: list[Any] = []

    if retriever is not None:
        try:
            result = retriever.search(message, top_k=10)
            # Handle both sync (Retriever) and async (HybridRetriever)
            if inspect.isawaitable(result):
                result = await result
            chunks = list(result.chunks) if result else []
        except Exception as exc:
            logger.warning(
                "rag_agent.retrieve_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                session_id=session_id,
            )
            chunks = []

    # ------------------------------------------------------------------
    # Step 2: Rerank with Cohere cross-encoder (top-5)
    # ------------------------------------------------------------------
    if cohere_reranker is not None and chunks:
        try:
            chunks = await cohere_reranker.rerank(message, chunks, top_n=5)
        except Exception as exc:
            # CohereReranker already handles its own graceful degradation,
            # but catch any unexpected failure here too.
            logger.warning(
                "rag_agent.rerank_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                session_id=session_id,
            )
            chunks = chunks[:5]

    # ------------------------------------------------------------------
    # Step 3: Build citations from chunks
    # ------------------------------------------------------------------
    citations: list[Any] = [citation_from_chunk(c) for c in chunks]

    # ------------------------------------------------------------------
    # Step 4: Generate grounded answer via LLM
    # ------------------------------------------------------------------
    response_text = ""
    mode = "no_llm"

    if llm_answer_service is not None and chunks:
        try:
            writer = None
            try:
                from langgraph.config import get_stream_writer
                writer = get_stream_writer()
            except Exception:
                writer = None

            stream_answer = getattr(llm_answer_service, "answer_stream", None)
            if writer is not None and callable(stream_answer):
                parts: list[str] = []
                async for token in stream_answer(
                    chunks=chunks,
                    citations=citations,
                    query=message,
                    language=language,
                    session_id=session_id,
                ):
                    parts.append(token)
                    writer({"type": "token", "content": token})
                response_text = "".join(parts)
                mode = "llm_stream"
            else:
                response = await llm_answer_service.answer(
                    chunks=chunks,
                    citations=citations,
                    query=message,
                    language=language,
                    session_id=session_id,
                )
                response_text = response.message
                mode = "llm"
        except Exception as exc:
            logger.warning(
                "rag_agent.llm_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                fallback=True,
                session_id=session_id,
            )
            response_text = ""
            mode = "llm_failed"

    # ------------------------------------------------------------------
    # Step 5: Fallback response when LLM unavailable or failed
    # ------------------------------------------------------------------
    if not response_text:
        if chunks:
            # Deterministic fallback: summarize first chunk(s)
            if language == "vi":
                response_text = (
                    f"Dựa trên thông tin có sẵn, đây là điều mình tìm được:\n\n"
                    f"**{chunks[0].title}**: {chunks[0].text[:300]}"
                )
                if len(chunks) > 1:
                    response_text += f"\n\n**{chunks[1].title}**: {chunks[1].text[:200]}"
            else:
                response_text = (
                    f"Based on available information, here is what I found:\n\n"
                    f"**{chunks[0].title}**: {chunks[0].text[:300]}"
                )
                if len(chunks) > 1:
                    response_text += f"\n\n**{chunks[1].title}**: {chunks[1].text[:200]}"
            mode = "deterministic"
        else:
            # No chunks available at all
            if language == "vi":
                response_text = (
                    "Mình chưa có thông tin cụ thể về khoản này, "
                    "nhưng bạn có thể hỏi thêm về văn hóa, lịch sử, "
                    "hoặc các địa điểm ở Hàm Ninh nhé!"
                )
            else:
                response_text = (
                    "I don't have specific information about this yet, "
                    "but feel free to ask about Ham Ninh's culture, history, "
                    "or places!"
                )
            mode = "no_chunks"

    # Store in semantic cache if enabled and response was successfully generated
    if (
        services.semantic_cache is not None
        and services.embedding_service is not None
        and response_text
        and mode in ("llm", "llm_stream", "deterministic")
    ):
        try:
            if query_embedding is None:
                embeddings = await services.embedding_service.embed_texts([message])
                query_embedding = embeddings[0] if embeddings else None
            if query_embedding is not None:
                cache_data = {
                    "response_text": response_text,
                    "knowledge_chunks": [c.model_dump() for c in chunks],
                    "citations": [cit.model_dump() for cit in citations],
                }
                await services.semantic_cache.store(
                    query=message,
                    query_embedding=query_embedding,
                    response=json.dumps(cache_data),
                )
        except Exception as exc:
            logger.warning(
                "rag_agent.semantic_cache_store_failed",
                error=str(exc),
                session_id=session_id,
            )

    elapsed = round((time.perf_counter() - t0) * 1000, 3)
    logger.info(
        "graph.node_exit",
        node="rag_agent",
        session_id=session_id,
        mode=mode,
        chunk_count=len(chunks),
        citation_count=len(citations),
        duration_ms=elapsed,
    )
    return {
        "knowledge_chunks": chunks,
        "citations": citations,
        "response_text": response_text,
        "run_status": "gathering",
        "current_step": "knowledge",
        "tool_receipts": [{
            "tool": "knowledge_retriever",
            "status": mode,
            "result_count": len(chunks),
        }],
    }


# ---------------------------------------------------------------------------
