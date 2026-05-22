"""Pydantic models for the RAG (Retrieval-Augmented Generation) corpus pipeline."""

from typing import Any
from pydantic import BaseModel, Field


class RAGChunk(BaseModel):
    """A single chunk of text from a source document, with full provenance metadata."""

    chunk_id: str = Field(
        description="SHA-256-based unique identifier for this chunk"
    )
    source_id: str = Field(
        description="Unique identifier for the source document"
    )
    title: str = Field(
        description="Title or heading of the source document"
    )
    url: str | None = Field(
        default=None,
        description="Optional URL pointing to the source document",
    )
    domain: str = Field(
        description="Domain or category the source belongs to (e.g. 'tourism', 'transport')"
    )
    source_type: str = Field(
        description="Type of the source (e.g. 'gov', 'blog', 'review')"
    )
    reliability: str = Field(
        description="Reliability tier (e.g. 'high', 'medium', 'low')"
    )
    language: str = Field(
        description="ISO 639-1 language code (e.g. 'vi', 'en')"
    )
    location: str = Field(
        description="Geographic location this chunk pertains to (e.g. 'Hàm Ninh', 'Phú Quốc')"
    )
    text: str = Field(
        description="The actual text content of this chunk"
    )
    chunk_index: int = Field(
        description="Zero-based index of this chunk within the source document"
    )
    total_chunks: int = Field(
        description="Total number of chunks in the source document"
    )
    topic: str | None = Field(
        default=None,
        description="Knowledge-base topic assigned during extraction",
    )
    entity_type: str | None = Field(
        default=None,
        description="Entity category assigned during extraction",
    )
    entity_name: str | None = Field(
        default=None,
        description="Entity name assigned during extraction",
    )
    evidence_type: str | None = Field(
        default=None,
        description="Evidence class for agent routing and filtering",
    )
    source_file: str | None = Field(
        default=None,
        description="Knowledge-base artifact that produced this chunk",
    )


class CorpusStats(BaseModel):
    """Aggregate statistics about a loaded and chunked RAG corpus."""

    total_docs: int = Field(
        description="Total number of source documents loaded"
    )
    total_chunks: int = Field(
        description="Total number of chunks after splitting all documents"
    )
    avg_chunk_length: float = Field(
        description="Average character length across all chunks"
    )
    source_type_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="Count of chunks per source_type",
    )
    reliability_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="Count of chunks per reliability tier",
    )


class RetrievalResult(BaseModel):
    """Result of a retrieval query against the RAG corpus."""

    chunks: list[RAGChunk] = Field(
        default_factory=list,
        description="Ranked list of retrieved chunks",
    )
    query: str = Field(
        description="The original query string"
    )
    total_found: int = Field(
        description="Total number of chunks matching the query"
    )
    latency_ms: float = Field(
        default=0.0,
        description="Query execution time in milliseconds",
    )
