"""FastAPI application entrypoint for Ham Ninh AI Assistant.

Wires together the lifespan manager, CORS middleware, structured logging,
router registration, and custom error handlers. Replaces the S02 stub.
"""

import os
import time
from collections.abc import AsyncGenerator, Callable
from typing import Any
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.middleware.auth import verify_api_key
from app.middleware.correlation import CorrelationIdMiddleware
from app.middleware.rate_limiter import get_limiter, rate_limit_exceeded_handler
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.chat import router as chat_router
from app.routers.health import router as health_router
from app.services.user_service import UserService
from app.services.langfuse_service import init_langfuse

from agents.tools.corpus_loader import load_corpus
from agents.graph.agent_service import AgentService, create_agent_checkpointer
from agents.tools.embedding_service import EmbeddingService
from agents.tools.hybrid_retriever import BM25Vectorizer, HybridRetriever
from agents.services.llm_answer_service import LLMAnswerService
from agents.services.place_recommendation_service import PlaceRecommendationService
from agents.tools.places_service import GooglePlacesService
from agents.tools.routes_service import GoongRoutesService
from agents.tools.qdrant_service import QdrantService
from agents.tools.retriever import Retriever

logger = get_logger(__name__)

# ── Lifespan manager ────────────────────────────────────────────────────

_langfuse_cleanup: Callable[[], None] | None = None
_langfuse_client: Any | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle: startup and shutdown coordination.

    Startup:
        1. Configure structured logging.
        2. Load and validate settings (fail-fast on missing required env vars).
        3. Initialize Langfuse client if API keys are configured.
        4. Load corpus and build retriever, store on app.state.
        5. Log ready message with app metadata.

    Shutdown:
        1. Flush and close Langfuse client.
        2. Log shutdown confirmation.
    """
    global _langfuse_cleanup, _langfuse_client

    # 1. Setup logging before anything else so all startup logs are structured
    settings = get_settings()
    setup_logging(
        log_level=settings.LOG_LEVEL,
        json_logs=settings.APP_ENV != "development",
    )

    # 2. Initialize Langfuse (graceful skip if keys absent)
    _langfuse_cleanup, _langfuse_client = init_langfuse(settings)
    app.state.langfuse_client = _langfuse_client

    # 3. Load corpus and build retriever (project root = backend/../)
    project_root = Path(__file__).resolve().parents[2]
    corpus_path = project_root / "data" / "tourism_documents.jsonl"

    try:
        chunks = load_corpus(str(corpus_path))
        retriever = Retriever(chunks)
        app.state.retriever = retriever

        # Compute and log corpus stats
        source_ids = set(c.source_id for c in chunks)
        logger.info(
            "corpus.loaded",
            total_docs=len(source_ids),
            total_chunks=len(chunks),
            corpus_path=str(corpus_path),
        )
    except Exception as exc:
        logger.error("corpus.load_failed", error=str(exc))
        # Don't crash — retriever will be absent, endpoint returns 503
        app.state.retriever = None
        chunks = []

    # 4. Wire hybrid retrieval (Qdrant + BM25 + dense embeddings)
    #    Gracefully degrades to keyword-only if Qdrant/OpenAI unavailable.
    app.state.hybrid_retriever = None
    app.state.bm25_vectorizer = None
    app.state.qdrant_service = None
    app.state.embedding_service = None
    app.state.llm_service = None
    app.state.places_service = None
    app.state.place_recommendation_service = None
    app.state.agent_service = None

    try:
        places_service = GooglePlacesService(settings=settings)
        routes_service = GoongRoutesService(settings=settings)
        app.state.places_service = places_service
        app.state.place_recommendation_service = PlaceRecommendationService(
            places_service, routes_service=routes_service
        )
        logger.info("places.recommendation_configured", provider="goong_places")
    except Exception as exc:
        logger.warning("places.recommendation_init_failed", error_type=type(exc).__name__)

    if chunks:
        try:
            qdrant_service = QdrantService()
            embedding_service = EmbeddingService()

            bm25 = BM25Vectorizer()
            bm25.fit([c.text for c in chunks])
            logger.info(
                "bm25.fit_complete",
                vocab_size=bm25.vocab_size,
                corpus_size=len(chunks),
            )

            hybrid_retriever = HybridRetriever(
                qdrant_service=qdrant_service,
                embedding_service=embedding_service,
                bm25=bm25,
                fallback=app.state.retriever,
            )

            app.state.hybrid_retriever = hybrid_retriever
            app.state.bm25_vectorizer = bm25
            app.state.qdrant_service = qdrant_service
            app.state.embedding_service = embedding_service
            app.state.llm_service = LLMAnswerService()
        except Exception as exc:
            logger.warning("hybrid.init_failed", error=str(exc))

    checkpoint, checkpoint_mode = await create_agent_checkpointer()
    app.state.agent_service = AgentService(
        retriever=app.state.retriever,
        hybrid_retriever=app.state.hybrid_retriever,
        llm_service=app.state.llm_service,
        checkpointer=checkpoint,
        checkpoint_mode=checkpoint_mode,
        place_recommendation_service=app.state.place_recommendation_service,
        langfuse_client=_langfuse_client,
    )

    # 5. Initialize UserService (PostgreSQL-backed auth)
    app.state.user_service = None
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        try:
            app.state.user_service = await UserService.create(dsn)
            logger.info("user_service.initialized", storage="postgres")
        except Exception as exc:
            logger.warning("user_service.init_failed", error=str(exc))

    logger.info(
        "app.startup",
        title=app.title,
        version=app.version,
        env=settings.APP_ENV,
        langfuse_enabled=_langfuse_cleanup is not None,
        langfuse_client_attached=_langfuse_client is not None,
        corpus_loaded=app.state.retriever is not None,
        llm_service_enabled=app.state.llm_service is not None,
        agent_service_enabled=app.state.agent_service is not None,
        place_recommendation_enabled=app.state.place_recommendation_service is not None,
        user_service_enabled=app.state.user_service is not None,
        checkpoint_mode=checkpoint_mode,
    )

    yield

    places_service = getattr(app.state, "places_service", None)
    places_client = getattr(places_service, "_client", None)
    close_client = getattr(places_client, "aclose", None)
    if close_client is not None:
        await close_client()

    # Close user service pool
    user_service = getattr(app.state, "user_service", None)
    if user_service is not None:
        await user_service.close()

    # Shutdown phase
    if _langfuse_cleanup:
        _langfuse_cleanup()

    logger.info("app.shutdown")


# ── Application factory ──────────────────────────────────────────────────

app = FastAPI(
    title="Ham Ninh AI Assistant",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ── Rate Limiter ────────────────────────────────────────────────────────

limiter = get_limiter()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


# ── Correlation ID middleware ────────────────────────────────────────────

# Added early so every log line (including error paths) carries a
# request_id. Extracts X-Request-ID from the client or generates one.
app.add_middleware(CorrelationIdMiddleware)


# ── CORS middleware ──────────────────────────────────────────────────────

# CORS is added via FastAPI's add_middleware which internally wraps the
# ASGI app. Origins come from Settings.CORS_ORIGINS.
settings_for_cors = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings_for_cors.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Structured request logging middleware ────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next: Callable) -> JSONResponse:
    """Log every request start and completion as structured JSON.

    Captures method, path, status_code, and duration_ms per request.
    """
    start = time.perf_counter()
    log = logger.bind(method=request.method, path=request.url.path)

    log.info("request.start")

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        log.error("request.error", duration_ms=duration_ms)
        raise

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    log.info(
        "request.end",
        status_code=response.status_code,
        duration_ms=duration_ms,
    )

    return response


# ── Router registration ─────────────────────────────────────────────────

# Health router — no auth required (used by orchestrator healthchecks)
app.include_router(health_router)

# Auth router — no auth required (register/login are public)
app.include_router(auth_router)

# Chat router — requires API key auth
app.include_router(chat_router, dependencies=[Depends(verify_api_key)])

# Admin router — each endpoint manages its own JWT auth via Depends(get_current_user)
app.include_router(admin_router)


# ── Root endpoint ───────────────────────────────────────────────────────

@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint — service identity and version."""
    return {"service": "Ham Ninh AI Assistant", "version": "0.1.0"}


# ── Custom exception handlers ───────────────────────────────────────────

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """Handle HTTPException with structured error response.

    Returns {"detail", "code", "path"} instead of plain text.
    Logs the error with correlation ID for traceability.
    """
    log = get_logger(__name__)
    log.warning(
        "http_exception",
        status_code=exc.status_code,
        detail=str(exc.detail),
        path=request.url.path,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "code": exc.status_code,
            "path": str(request.url.path),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Handle request validation errors with structured detail.

    Returns per-field error information in a machine-readable format.
    Logs the validation failure with correlation ID for traceability.
    """
    errors = []
    for error in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        })

    log = get_logger(__name__)
    log.warning(
        "request.validation_error",
        path=request.url.path,
        error_count=len(errors),
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Request validation failed",
            "code": 422,
            "path": str(request.url.path),
            "errors": errors,
        },
    )
