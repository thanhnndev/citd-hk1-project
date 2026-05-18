"""Admin endpoints — corpus embedding and management operations.

POST /admin/embed triggers full corpus ingestion into Qdrant:
  loads tourism_documents.jsonl → embeds via OpenAI → upserts to Qdrant.
"""

import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status

from app.core.logging import get_logger
from app.models.response import EmbedResponse
from app.services.corpus_loader import load_corpus
from app.services.embedding_service import EmbeddingService
from app.services.hybrid_retriever import BM25Vectorizer
from app.services.qdrant_service import (
    COLLECTION_NAME,
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    VECTOR_SIZE,
    QdrantService,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/embed", response_model=EmbedResponse, status_code=status.HTTP_200_OK)
async def embed_corpus(request: Request) -> EmbedResponse:
    """Trigger full corpus ingestion into Qdrant.

    Loads the tourism JSONL corpus, embeds all chunks via OpenAI
    text-embedding-3-small, and upserts them into the Qdrant collection
    using named dense+sparse vectors.

    Returns:
        EmbedResponse with corpus stats and latency.

    Raises:
        HTTPException 500: If the corpus file is missing or empty.
    """
    start = time.monotonic()

    # Resolve corpus path — works both locally and inside Docker container.
    # Local:  backend/app/routers/admin.py → parents[3] = project root → data/
    # Docker: /app/app/routers/admin.py   → /data/ mounted at container root
    _admin_file = Path(__file__).resolve()
    _project_root = _admin_file.parents[3]
    corpus_path = _project_root / "data" / "tourism_documents.jsonl"
    if not corpus_path.exists():
        # Fallback for Docker where data/ is mounted at filesystem root
        corpus_path = Path("/data/tourism_documents.jsonl")

    logger.info("embed.started", corpus_path=str(corpus_path))

    try:
        chunks = load_corpus(str(corpus_path))
    except FileNotFoundError as exc:
        logger.error("embed.corpus_not_found", path=str(corpus_path))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Corpus file not found: {corpus_path}",
        ) from exc

    if not chunks:
        logger.error("embed.corpus_empty", path=str(corpus_path))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Corpus loaded but contains no chunks.",
        )

    embedding_svc = EmbeddingService()
    qdrant_svc = QdrantService()

    await qdrant_svc.ensure_hybrid_collection()

    texts = [c.text for c in chunks]
    vectors = await embedding_svc.embed_texts(texts)

    bm25 = BM25Vectorizer()
    bm25.fit(texts)

    count = await qdrant_svc.upsert_hybrid_chunks(chunks, vectors, bm25)

    # Keep in-process vectorizer in sync with freshly upserted corpus
    request.app.state.bm25_vectorizer = bm25

    latency_ms = (time.monotonic() - start) * 1000

    logger.info(
        "embed.done",
        total_chunks=count,
        latency_ms=round(latency_ms, 2),
    )

    return EmbedResponse(
        total_docs=len({c.source_id for c in chunks}),
        total_chunks=count,
        vector_dim=VECTOR_SIZE,
        collection_name=COLLECTION_NAME,
        latency_ms=round(latency_ms, 2),
    )
