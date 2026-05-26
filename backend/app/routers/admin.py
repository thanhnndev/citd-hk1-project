"""Admin endpoints — corpus embedding and management operations.

POST /admin/embed triggers full corpus ingestion into Qdrant:
  loads tourism_documents.jsonl → embeds via OpenAI → upserts to Qdrant.

POST /admin/eval/trigger runs RAGAS evaluation against eval_dataset.jsonl.
GET /admin/eval/results lists recent evaluation result files.
GET /admin/traces is a stub for S04 Langfuse integration.
"""

import json
import os
import time
from pathlib import Path

import openai
from qdrant_client.http.exceptions import UnexpectedResponse

from fastapi import APIRouter, HTTPException, Request, status, Depends

from app.core.logging import get_logger
from app.core.config import get_settings
from app.models.response import (
    AdminStatsResponse,
    EmbedResponse,
    EvalTriggerRequest,
    EvalResultResponse,
    EvalFileListing,
    TracesStatusResponse,
    FairnessSummaryResponse,
)
from app.middleware.auth import get_current_user
from agents.tools.corpus_loader import load_proposition_corpus
from agents.tools.embedding_service import EmbeddingService, EmbeddingValidationError
from agents.tools.hybrid_retriever import BM25Vectorizer
from agents.tools.qdrant_service import (
    COLLECTION_NAME,
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    VECTOR_SIZE,
    QdrantService,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/embed", response_model=EmbedResponse, status_code=status.HTTP_200_OK)
async def embed_corpus(
    request: Request,
    current_user=Depends(get_current_user),
) -> EmbedResponse:
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
        chunks = load_proposition_corpus(str(corpus_path))
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

    texts = [c.text for c in chunks]

    # Compute language distribution for observability
    from collections import Counter
    lang_dist: dict[str, int] = dict(Counter(c.language for c in chunks))

    try:
        await qdrant_svc.ensure_hybrid_collection()
        vectors = await embedding_svc.embed_texts(texts)

        bm25 = BM25Vectorizer()
        bm25.fit(texts)

        count = await qdrant_svc.upsert_hybrid_chunks(chunks, vectors, bm25)
    except EmbeddingValidationError as exc:
        logger.error(
            "embed.embedding_validation_failed",
            error=str(exc),
            expected_dim=VECTOR_SIZE,
            expected_count=len(texts),
            language_distribution=lang_dist,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "embedding_validation_failed",
                "message": str(exc),
                "expected_dim": VECTOR_SIZE,
                "expected_count": len(texts),
            },
        ) from exc
    except openai.OpenAIError as exc:
        logger.error(
            "embed.openai_failed",
            error_type=type(exc).__name__,
            expected_dim=VECTOR_SIZE,
            expected_count=len(texts),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "openai_dependency_failed",
                "message": "OpenAI embeddings request failed.",
                "error_type": type(exc).__name__,
            },
        ) from exc
    except UnexpectedResponse as exc:
        logger.error(
            "embed.qdrant_failed",
            error_type=type(exc).__name__,
            collection=COLLECTION_NAME,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "qdrant_dependency_failed",
                "message": "Qdrant request failed.",
                "collection_name": COLLECTION_NAME,
                "dense_vector_name": DENSE_VECTOR_NAME,
            },
        ) from exc
    except Exception as exc:
        if exc.__class__.__module__.startswith("qdrant_client"):
            logger.error(
                "embed.qdrant_failed",
                error_type=type(exc).__name__,
                collection=COLLECTION_NAME,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": "qdrant_dependency_failed",
                    "message": "Qdrant request failed.",
                    "collection_name": COLLECTION_NAME,
                    "dense_vector_name": DENSE_VECTOR_NAME,
                },
            ) from exc
        raise

    # Keep in-process vectorizer in sync with freshly upserted corpus
    request.app.state.bm25_vectorizer = bm25

    latency_ms = (time.monotonic() - start) * 1000

    logger.info(
        "embed.done",
        total_docs=len({c.source_id for c in chunks}),
        total_chunks=count,
        propositions_ingested=count,
        language_distribution=lang_dist,
        latency_ms=round(latency_ms, 2),
    )

    return EmbedResponse(
        total_docs=len({c.source_id for c in chunks}),
        total_chunks=count,
        propositions_ingested=count,
        language_distribution=lang_dist,
        vector_dim=VECTOR_SIZE,
        collection_name=COLLECTION_NAME,
        latency_ms=round(latency_ms, 2),
    )


# ---------------------------------------------------------------------------
# RAGAS Evaluation endpoints
# ---------------------------------------------------------------------------

_DEFAULT_EVAL_DATASET = "data/eval_dataset.jsonl"


def _resolve_eval_dataset_path(requested: str | None) -> str:
    """Resolve eval dataset path — works both locally and inside Docker."""
    if requested:
        return requested

    _admin_file = Path(__file__).resolve()
    _project_root = _admin_file.parents[3]
    candidate = _project_root / _DEFAULT_EVAL_DATASET
    if candidate.exists():
        return str(candidate)
    # Fallback: Docker volume mount
    return _DEFAULT_EVAL_DATASET


@router.post(
    "/eval/trigger",
    response_model=EvalResultResponse,
    status_code=status.HTTP_200_OK,
)
async def trigger_eval(
    body: EvalTriggerRequest | None = None,
    request: Request = None,
    current_user=Depends(get_current_user),
) -> EvalResultResponse:
    """Run RAGAS evaluation against eval_dataset.jsonl.

    Requires JWT auth. Returns credential_blocked verdict if OPENAI_API_KEY
    is not configured. Synchronous call — may block ~30s for 10-15 questions.

    Returns:
        EvalResultResponse with verdict, metrics, timestamp, and result path.
    """
    from agents.ml.ragas_evaluator import RAGASEvaluator

    openai_key = os.environ.get("OPENAI_API_KEY")
    dataset_path = _resolve_eval_dataset_path(
        body.dataset_path if body else None
    )
    metrics = body.metrics if body else None

    logger.info(
        "eval.trigger",
        user_id=getattr(current_user, "id", "unknown"),
        dataset_path=dataset_path,
        metrics=metrics,
    )

    evaluator = RAGASEvaluator(
        openai_api_key=openai_key,
        metrics=metrics,
        corpus_path=_resolve_eval_dataset_path(None).replace(
            "eval_dataset.jsonl", "tourism_documents.jsonl"
        ),
    )
    result = evaluator.evaluate(dataset_path)

    latency_ms = result.get("latency_seconds", 0) * 1000

    logger.info(
        "eval.completed",
        verdict=result.get("verdict"),
        latency_ms=round(latency_ms, 2),
    )

    return EvalResultResponse(
        verdict=result.get("verdict", "unknown"),
        metrics=result.get("metrics", {}),
        timestamp=result.get("timestamp", ""),
        dataset_size=result.get("dataset_size", 0),
        latency_ms=round(latency_ms, 2),
        result_path=result.get("saved_to"),
    )


@router.get("/eval/results", response_model=list[EvalFileListing])
async def list_eval_results(
    current_user=Depends(get_current_user),
) -> list[EvalFileListing]:
    """List recent evaluation results from data/eval_results/.

    Requires JWT auth. Returns empty list if no results exist.
    """
    results_dir = Path("data/eval_results")
    if not results_dir.exists():
        return []

    listings: list[EvalFileListing] = []
    for fpath in sorted(results_dir.glob("eval_*.json"), reverse=True):
        try:
            with open(fpath, encoding="utf-8") as fh:
                data = json.load(fh)
            listings.append(
                EvalFileListing(
                    filename=fpath.name,
                    timestamp=data.get("timestamp", ""),
                    verdict=data.get("verdict", "unknown"),
                    dataset_size=data.get("dataset_size", 0),
                )
            )
        except (json.JSONDecodeError, OSError):
            continue

    return listings


@router.get("/traces", response_model=TracesStatusResponse)
async def get_traces(
    request: Request,
    current_user=Depends(get_current_user),
) -> TracesStatusResponse:
    """Return Langfuse tracing status for observability diagnostics.

    Checks whether the Langfuse client was successfully initialized
    during app startup. Returns host and enabled flag.
    """
    settings = get_settings()
    langfuse_client = getattr(request.app.state, "langfuse_client", None)

    if langfuse_client is not None:
        return TracesStatusResponse(
            langfuse_enabled=True,
            host=settings.LANGFUSE_HOST,
            message="Langfuse tracing is active.",
        )

    return TracesStatusResponse(
        langfuse_enabled=False,
        host=None,
        message="Langfuse not configured — set LANGFUSE_* env vars",
    )


@router.get("/fairness", response_model=FairnessSummaryResponse)
async def get_fairness(
    current_user=Depends(get_current_user),
) -> FairnessSummaryResponse:
    """Return fairness audit summary for social impact diagnostics.

    Reads all JSONL snapshots from data/fairness_audit/ and returns
    total_audits count, latest timestamp, and aggregated local_factor
    distribution with buckets, mean, and count.
    """
    _admin_file = Path(__file__).resolve()
    _project_root = _admin_file.parents[3]
    audit_dir = _project_root / "data" / "fairness_audit"

    if not audit_dir.exists():
        return FairnessSummaryResponse(
            total_audits=0,
            latest_timestamp=None,
            local_factor_distribution=None,
            message="No fairness audits recorded yet",
        )

    audit_files = sorted(audit_dir.glob("*.jsonl"))
    if not audit_files:
        return FairnessSummaryResponse(
            total_audits=0,
            latest_timestamp=None,
            local_factor_distribution=None,
            message="No fairness audits recorded yet",
        )

    # Aggregate across all audit files
    all_local_factors: list[float] = []
    latest_timestamp: str | None = None

    for fpath in audit_files:
        try:
            with open(fpath, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    ts = record.get("timestamp")
                    if ts and (latest_timestamp is None or ts > latest_timestamp):
                        latest_timestamp = ts
                    # Collect individual local_factors if present as list
                    local_factors = record.get("local_factors")
                    if isinstance(local_factors, list) and local_factors:
                        all_local_factors.extend(float(lf) for lf in local_factors)
                    elif "local_factor" in record:
                        all_local_factors.append(float(record["local_factor"]))
        except (json.JSONDecodeError, OSError, ValueError):
            continue

    total_audits = len(audit_files)

    if not all_local_factors:
        return FairnessSummaryResponse(
            total_audits=total_audits,
            latest_timestamp=latest_timestamp,
            local_factor_distribution=None,
            message="No local_factor data found in audit files",
        )

    # Compute aggregate distribution
    count = len(all_local_factors)
    mean_val = sum(all_local_factors) / count
    buckets = _bucket_local_factors_aggregate(all_local_factors)

    local_factor_dist = {
        "buckets": buckets,
        "mean": round(mean_val, 4),
        "count": count,
    }

    return FairnessSummaryResponse(
        total_audits=total_audits,
        latest_timestamp=latest_timestamp,
        local_factor_distribution=local_factor_dist,
        message=None,
    )


def _bucket_local_factors_aggregate(local_factors: list[float]) -> dict[str, int]:
    """Bucket local_factor values into the plan-specified distribution ranges."""
    buckets: dict[str, int] = {
        "<0.1": 0,
        "0.1-0.3": 0,
        "0.3-0.5": 0,
        ">0.5": 0,
    }
    for lf in local_factors:
        if lf < 0.1:
            buckets["<0.1"] += 1
        elif lf < 0.3:
            buckets["0.1-0.3"] += 1
        elif lf < 0.5:
            buckets["0.3-0.5"] += 1
        else:
            buckets[">0.5"] += 1
    return buckets


# ---------------------------------------------------------------------------
# Stats endpoint — corpus operational visibility
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=AdminStatsResponse)
async def get_stats(
    request: Request,
    current_user=Depends(get_current_user),
) -> AdminStatsResponse:
    """Return corpus operational stats for admin dashboard visibility.

    Requires JWT auth. Reads from app.state for retriever, BM25, hybrid,
    and Qdrant service status. Returns safe defaults when components are
    not yet initialized.
    """
    retriever = getattr(request.app.state, "retriever", None)
    bm25 = getattr(request.app.state, "bm25_vectorizer", None)
    hybrid = getattr(request.app.state, "hybrid_retriever", None)
    qdrant = getattr(request.app.state, "qdrant_service", None)

    # Retrieve chunk and doc counts from the in-process retriever
    total_chunks = 0
    total_docs = 0
    language_distribution: dict[str, int] = {}

    if retriever is not None:
        chunks = getattr(retriever, "chunks", [])
        total_chunks = len(chunks)
        source_ids = set()
        lang_counter: dict[str, int] = {}
        for c in chunks:
            source_ids.add(getattr(c, "source_id", ""))
            lang = getattr(c, "language", "unknown")
            lang_counter[lang] = lang_counter.get(lang, 0) + 1
        total_docs = len(source_ids)
        language_distribution = lang_counter

    bm25_vocab_size = 0
    if bm25 is not None:
        bm25_vocab_size = getattr(bm25, "vocab_size", 0)

    hybrid_enabled = hybrid is not None

    qdrant_collection_name: str | None = None
    if qdrant is not None:
        qdrant_collection_name = getattr(qdrant, "collection_name", None)

    logger.info(
        "stats.read",
        user_id=getattr(current_user, "id", "unknown"),
        total_chunks=total_chunks,
        total_docs=total_docs,
        bm25_vocab_size=bm25_vocab_size,
        hybrid_enabled=hybrid_enabled,
    )

    return AdminStatsResponse(
        total_chunks=total_chunks,
        total_docs=total_docs,
        language_distribution=language_distribution,
        bm25_vocab_size=bm25_vocab_size,
        hybrid_enabled=hybrid_enabled,
        qdrant_collection_name=qdrant_collection_name,
    )
