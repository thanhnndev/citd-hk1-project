"""Qdrant vector store service for the tourism RAG pipeline.

Wraps AsyncQdrantClient with collection lifecycle management, bulk upsert,
and semantic search. All operations emit structured log events for observability.
"""

import time

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    Fusion,
    FusionQuery,
    PointStruct,
    Prefetch,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from app.core.config import get_settings
from app.models.rag import RAGChunk

logger = structlog.get_logger(__name__)

COLLECTION_NAME = "tourism_chunks"
VECTOR_SIZE = 1536
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"


class QdrantService:
    """Async wrapper around Qdrant for the tourism RAG corpus.

    Usage::

        svc = QdrantService()
        await svc.ensure_collection()
        count = await svc.upsert_chunks(chunks, vectors)
        results = await svc.search(query_vector, top_k=5)

        # Hybrid (dense + sparse) workflow:
        await svc.ensure_hybrid_collection()
        count = await svc.upsert_hybrid_chunks(chunks, dense_vectors, bm25)
        results = await svc.hybrid_search(dense_vector, sparse_vector, top_k=5)
    """

    def __init__(self, url: str | None = None) -> None:
        self._client = AsyncQdrantClient(url=url or get_settings().qdrant_url)

    async def ensure_collection(self) -> None:
        """Create the collection if it does not already exist.

        Uses cosine distance with VECTOR_SIZE-dim dense vectors.
        Logs qdrant.collection_ensured with created/existed status.
        """
        exists = await self._client.collection_exists(COLLECTION_NAME)
        if not exists:
            await self._client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )
            logger.info("qdrant.collection_ensured", collection=COLLECTION_NAME, status="created")
        else:
            logger.info("qdrant.collection_ensured", collection=COLLECTION_NAME, status="existed")

    async def upsert_chunks(
        self, chunks: list[RAGChunk], vectors: list[list[float]]
    ) -> int:
        """Upsert RAGChunk objects with their embedding vectors into Qdrant.

        Each point gets an integer id (0..N-1) and a payload containing all
        RAGChunk fields for retrieval without a secondary DB lookup.

        Args:
            chunks: List of RAGChunk objects to index.
            vectors: Corresponding embedding vectors (same length as chunks).

        Returns:
            Number of points upserted.
        """
        points = [
            PointStruct(
                id=idx,
                vector=vector,
                payload={
                    "chunk_id": chunk.chunk_id,
                    "source_id": chunk.source_id,
                    "title": chunk.title,
                    "url": chunk.url,
                    "domain": chunk.domain,
                    "source_type": chunk.source_type,
                    "reliability": chunk.reliability,
                    "language": chunk.language,
                    "location": chunk.location,
                    "text": chunk.text,
                    "chunk_index": chunk.chunk_index,
                    "total_chunks": chunk.total_chunks,
                },
            )
            for idx, (chunk, vector) in enumerate(zip(chunks, vectors))
        ]

        await self._client.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
            wait=True,
        )

        logger.info(
            "qdrant.upsert_complete",
            collection=COLLECTION_NAME,
            points_count=len(points),
        )
        return len(points)

    async def search(
        self, query_vector: list[float], top_k: int = 5
    ) -> list:
        """Run a cosine similarity search against the collection.

        Args:
            query_vector: Dense query embedding (1536-dim).
            top_k: Maximum number of results to return.

        Returns:
            Raw list of ScoredPoint objects from qdrant-client.
        """
        results = await self._client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vector,
            limit=top_k,
            with_payload=True,
            with_vectors=True,
        )

        logger.info(
            "qdrant.search_complete",
            collection=COLLECTION_NAME,
            top_k=top_k,
            result_count=len(results),
        )
        return results

    async def ensure_hybrid_collection(self) -> None:
        """Create or migrate the collection to support named dense+sparse vectors.

        - Absent: creates with named dense + sparse vector configs.
        - Exists with 'dense' key: already hybrid, no-op.
        - Exists with unnamed schema: deletes and recreates with named schema,
          logging hybrid.collection_migrated.
        """
        exists = await self._client.collection_exists(COLLECTION_NAME)
        if not exists:
            await self._client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config={
                    DENSE_VECTOR_NAME: VectorParams(
                        size=VECTOR_SIZE, distance=Distance.COSINE
                    )
                },
                sparse_vectors_config={
                    SPARSE_VECTOR_NAME: SparseVectorParams()
                },
            )
            logger.info(
                "qdrant.collection_ensured",
                collection=COLLECTION_NAME,
                status="created_hybrid",
            )
            return

        info = await self._client.get_collection(COLLECTION_NAME)
        vectors_cfg = info.config.params.vectors

        # Already a named-vector (hybrid) schema
        if isinstance(vectors_cfg, dict) and DENSE_VECTOR_NAME in vectors_cfg:
            logger.info(
                "qdrant.collection_ensured",
                collection=COLLECTION_NAME,
                status="existed_hybrid",
            )
            return

        # Old unnamed schema — migrate
        await self._client.delete_collection(COLLECTION_NAME)
        await self._client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                DENSE_VECTOR_NAME: VectorParams(
                    size=VECTOR_SIZE, distance=Distance.COSINE
                )
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: SparseVectorParams()
            },
        )
        logger.info(
            "hybrid.collection_migrated",
            collection=COLLECTION_NAME,
            old_schema="unnamed",
            new_schema="named",
        )

    async def upsert_hybrid_chunks(
        self,
        chunks: list[RAGChunk],
        dense_vectors: list[list[float]],
        bm25: "BM25Vectorizer",  # type: ignore[name-defined]  # imported at call site
    ) -> int:
        """Upsert chunks with both dense and sparse (BM25) vectors.

        Args:
            chunks: RAGChunk objects to index.
            dense_vectors: Corresponding dense embeddings (same length as chunks).
            bm25: Fitted BM25Vectorizer used to encode each chunk text.

        Returns:
            Number of points upserted.
        """
        t0 = time.perf_counter()
        points = [
            PointStruct(
                id=idx,
                vector={
                    DENSE_VECTOR_NAME: dense_vectors[idx],
                    SPARSE_VECTOR_NAME: bm25.encode(chunk.text),
                },
                payload={
                    "chunk_id": chunk.chunk_id,
                    "source_id": chunk.source_id,
                    "title": chunk.title,
                    "url": chunk.url,
                    "domain": chunk.domain,
                    "source_type": chunk.source_type,
                    "reliability": chunk.reliability,
                    "language": chunk.language,
                    "location": chunk.location,
                    "text": chunk.text,
                    "chunk_index": chunk.chunk_index,
                    "total_chunks": chunk.total_chunks,
                },
            )
            for idx, chunk in enumerate(chunks)
        ]

        await self._client.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
            wait=True,
        )

        latency_ms = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "embed.upsert_hybrid_complete",
            collection=COLLECTION_NAME,
            points_count=len(points),
            latency_ms=latency_ms,
        )
        return len(points)

    async def hybrid_search(
        self,
        dense_vector: list[float],
        sparse_vector: SparseVector,
        top_k: int = 5,
    ) -> list:
        """Run hybrid RRF-fused dense+sparse search via Qdrant query_points.

        Args:
            dense_vector: Dense query embedding.
            sparse_vector: BM25-encoded sparse query vector.
            top_k: Maximum number of fused results to return.

        Returns:
            List of ScoredPoint objects from qdrant-client.
        """
        t0 = time.perf_counter()
        results = await self._client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[
                Prefetch(
                    query=dense_vector,
                    using=DENSE_VECTOR_NAME,
                    limit=top_k * 4,
                ),
                Prefetch(
                    query=sparse_vector,
                    using=SPARSE_VECTOR_NAME,
                    limit=top_k * 4,
                ),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=top_k,
            with_payload=True,
        )

        latency_ms = round((time.perf_counter() - t0) * 1000, 3)
        logger.info(
            "hybrid.search_complete",
            collection=COLLECTION_NAME,
            top_k=top_k,
            result_count=len(results.points),
            latency_ms=latency_ms,
        )
        return results.points

    async def collection_info(self) -> dict:
        """Return basic health stats for the collection.

        Returns:
            Dict with points_count and vectors_count keys.
        """
        info = await self._client.get_collection(COLLECTION_NAME)
        return {
            "points_count": info.points_count,
            "vectors_count": info.vectors_count,
        }
