from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# NodeServices — dependency injection container
# ---------------------------------------------------------------------------


@dataclass
class NodeServices:
    """Container for injected dependencies used by LLM-dependent nodes.

    The graph assembler (T02) constructs a ``NodeServices`` instance with
    the real OpenAI client, retriever, and places service, then calls
    ``configure_services(services)`` before compiling the graph.
    """

    llm_client: Any = None  # openai.AsyncOpenAI or None
    model: str = "gpt-4o-mini"
    retriever: Any = None  # Retriever or HybridRetriever or None
    places_service: Any = None  # PlaceRecommendationService or None
    cohere_reranker: Any = None  # CohereReranker or None (graceful degradation)
    llm_answer_service: Any = None  # LLMAnswerService or None
    semantic_cache: Any = None  # SemanticCache or None
    embedding_service: Any = None  # EmbeddingService or None


_default_services = NodeServices()


def configure_services(services: NodeServices) -> None:
    """Set the module-level NodeServices singleton.

    Called by the graph assembler (T02) before compiling the StateGraph.
    """
    global _default_services
    _default_services = services


def get_services() -> NodeServices:
    """Return the current module-level NodeServices singleton."""
    return _default_services


# ---------------------------------------------------------------------------
