"""Shared pytest fixtures for corpus and retrieval tests."""

import os
from pathlib import Path

import pytest

from app.services.corpus_loader import load_corpus
from app.services.retriever import Retriever
from app.services.qdrant_service import QdrantService
from app.services.embedding_service import EmbeddingService

# Ensure required app secrets are set before any app module imports.
# Google credentials are optional and should remain absent unless a test opts in.
os.environ["OPENAI_API_KEY"] = "fake-test-key"


def _resolve_corpus_path() -> str:
    """Resolve the tourism_documents.jsonl path from either backend/ or project root."""
    p = Path("data/tourism_documents.jsonl")
    if not p.exists():
        p = Path(__file__).resolve().parent.parent.parent / "data" / "tourism_documents.jsonl"
    return str(p)


@pytest.fixture(scope="session")
def loaded_chunks():
    """Load and cache the full tourism corpus for the test session."""
    return load_corpus(_resolve_corpus_path())


@pytest.fixture(scope="session")
def sample_queries():
    """Known Hàm Ninh tourism queries for retrieval testing."""
    return [
        "làng chài Hàm Ninh",
        "Hàm Ninh hải sản",
        "chợ đêm Hàm Ninh",
    ]


@pytest.fixture(scope="session")
def retriever(loaded_chunks):
    """Provide a ready Retriever instance over the full corpus."""
    return Retriever(loaded_chunks)


@pytest.fixture(scope="session")
def qdrant_service():
    """QdrantService pointed at the test Qdrant instance."""
    return QdrantService(url=os.environ.get("QDRANT_URL", "http://localhost:46333"))


@pytest.fixture(scope="session")
def embedding_service():
    """EmbeddingService — only usable in integration tests with a real API key."""
    return EmbeddingService()
