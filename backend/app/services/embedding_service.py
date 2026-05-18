"""OpenAI embedding service for the tourism RAG pipeline.

Wraps the OpenAI Embeddings API with batching, rate-limit courtesy sleep,
and structured logging for observability.
"""

import asyncio
from typing import List

import structlog

import openai

from app.core.config import get_settings
from app.services.qdrant_service import VECTOR_SIZE

logger = structlog.get_logger(__name__)

class EmbeddingValidationError(RuntimeError):
    """Raised when the embedding provider returns an unusable response shape."""



class EmbeddingService:
    """Async wrapper around OpenAI text-embedding-3-small (or configured model).

    Usage::

        svc = EmbeddingService()
        vectors = await svc.embed_texts(["text one", "text two"])
        query_vec = await svc.embed_query("Hàm Ninh hải sản")
    """

    BATCH_SIZE = 100

    def __init__(self) -> None:
        settings = get_settings()
        self._client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model: str = settings.OPENAI_EMBEDDING_MODEL

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of texts, batching at BATCH_SIZE per API call.

        A 0.5 s courtesy sleep is inserted between batches to stay within
        OpenAI rate limits during bulk ingestion.

        Args:
            texts: Arbitrary-length list of strings to embed.

        Returns:
            List of 1536-dim float vectors in the same order as *texts*.
        """
        all_vectors: List[List[float]] = []

        batches = [
            texts[i : i + self.BATCH_SIZE]
            for i in range(0, len(texts), self.BATCH_SIZE)
        ]

        for batch_index, batch in enumerate(batches):
            if batch_index > 0:
                await asyncio.sleep(0.5)

            response = await self._client.embeddings.create(
                input=batch,
                model=self.model,
            )

            batch_vectors = [item.embedding for item in response.data]
            if len(batch_vectors) != len(batch):
                logger.error(
                    "embed.response_count_mismatch",
                    batch_index=batch_index,
                    expected_count=len(batch),
                    actual_count=len(batch_vectors),
                    model=self.model,
                )
                raise EmbeddingValidationError(
                    "Embedding response count mismatch: "
                    f"expected {len(batch)}, got {len(batch_vectors)}"
                )

            for vector_index, vector in enumerate(batch_vectors):
                if len(vector) != VECTOR_SIZE:
                    logger.error(
                        "embed.vector_dimension_mismatch",
                        batch_index=batch_index,
                        vector_index=vector_index,
                        expected_dim=VECTOR_SIZE,
                        actual_dim=len(vector),
                        model=self.model,
                    )
                    raise EmbeddingValidationError(
                        "Embedding vector dimension mismatch: "
                        f"expected {VECTOR_SIZE}, got {len(vector)} "
                        f"at batch {batch_index} index {vector_index}"
                    )
            all_vectors.extend(batch_vectors)

            logger.info(
                "embed.batch_complete",
                batch_index=batch_index,
                batch_size=len(batch),
                total_so_far=len(all_vectors),
                model=self.model,
            )

        return all_vectors

    async def embed_query(self, text: str) -> List[float]:
        """Embed a single query string.

        Convenience wrapper around :meth:`embed_texts` for the common
        single-text case (e.g. user search queries).

        Args:
            text: The query string to embed.

        Returns:
            A single 1536-dim float vector.
        """
        vectors = await self.embed_texts([text])
        return vectors[0]
