"""FastAPI application entrypoint for Ham Ninh AI Assistant.

Wires together the lifespan manager, CORS middleware, structured logging,
router registration, and custom error handlers. Replaces the S02 stub.
"""

import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.middleware.auth import verify_api_key
from app.routers.admin import router as admin_router
from app.routers.chat import router as chat_router
from app.routers.health import router as health_router
from app.services.langfuse_service import init_langfuse

logger = get_logger(__name__)

# ── Lifespan manager ────────────────────────────────────────────────────

_langfuse_cleanup: Callable[[], None] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle: startup and shutdown coordination.

    Startup:
        1. Configure structured logging.
        2. Load and validate settings (fail-fast on missing required env vars).
        3. Initialize Langfuse client if API keys are configured.
        4. Log ready message with app metadata.

    Shutdown:
        1. Flush and close Langfuse client.
        2. Log shutdown confirmation.
    """
    global _langfuse_cleanup

    # 1. Setup logging before anything else so all startup logs are structured
    settings = get_settings()
    setup_logging(
        log_level=settings.LOG_LEVEL,
        json_logs=settings.APP_ENV != "development",
    )

    # 2. Initialize Langfuse (graceful skip if keys absent)
    _langfuse_cleanup = init_langfuse(settings)

    logger.info(
        "app.startup",
        title=app.title,
        version=app.version,
        env=settings.APP_ENV,
        langfuse_enabled=_langfuse_cleanup is not None,
    )

    yield

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

# Chat router — requires API key auth
app.include_router(chat_router, dependencies=[Depends(verify_api_key)])

# Admin router — requires API key auth
app.include_router(admin_router, dependencies=[Depends(verify_api_key)])


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
    """
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
    """
    errors = []
    for error in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        })

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Request validation failed",
            "code": 422,
            "path": str(request.url.path),
            "errors": errors,
        },
    )
