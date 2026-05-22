"""OpenAI-compatible embedding service for the tourism RAG pipeline.

Wraps OpenAI-compatible Embeddings APIs with batching, dimension validation,
and structured logging for observability.
"""

import asyncio
from typing import List

import structlog

import openai

from app.core.config import get_settings
logger = structlog.get_logger(__name__)

class EmbeddingValidationError(RuntimeError):
    """Raised when the embedding provider returns an unusable response shape."""



class EmbeddingService:
    """Async wrapper around the configured OpenAI-compatible embedding model.

    Usage::

        svc = EmbeddingService()
        vectors = await svc.embed_texts(["text one", "text two"])
        query_vec = await svc.embed_query("Hàm Ninh hải sản")
    """

    BATCH_SIZE = 100

    def __init__(self) -> None:
        settings = get_settings()
        client_kwargs = {"api_key": settings.embedding_api_key}
        if settings.EMBEDDING_BASE_URL:
            client_kwargs["base_url"] = settings.EMBEDDING_BASE_URL
        self._client = openai.AsyncOpenAI(**client_kwargs)
        self.model: str = settings.embedding_model
        self.dimensions: int = settings.EMBEDDING_DIMENSIONS
        self.batch_size: int = max(1, settings.EMBEDDING_BATCH_SIZE)

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
            texts[i : i + self.batch_size]
            for i in range(0, len(texts), self.batch_size)
        ]

        for batch_index, batch in enumerate(batches):
            if batch_index > 0:
                await asyncio.sleep(0.5)

            response = await self._client.embeddings.create(
                input=batch,
                model=self.model,
                dimensions=self.dimensions,
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
                if len(vector) != self.dimensions:
                    logger.error(
                        "embed.vector_dimension_mismatch",
                        batch_index=batch_index,
                        vector_index=vector_index,
                        expected_dim=self.dimensions,
                        actual_dim=len(vector),
                        model=self.model,
                    )
                    raise EmbeddingValidationError(
                        "Embedding vector dimension mismatch: "
                        f"expected {self.dimensions}, got {len(vector)} "
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
