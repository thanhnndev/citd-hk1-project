"""Rate limiter middleware using slowapi with Redis backend.

Provides per-IP rate limiting with configurable limits per endpoint.
Falls back to in-memory storage if Redis is unavailable.
"""

from __future__ import annotations

import structlog
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import get_settings

logger = structlog.get_logger(__name__)


def _create_limiter() -> Limiter:
    """Create a slowapi Limiter instance.

    Attempts to use Redis as the storage backend. Falls back to
    in-memory if Redis URL is not configured or connection fails.
    """
    settings = get_settings()
    storage_uri = settings.redis_url

    try:
        limiter = Limiter(
            key_func=get_remote_address,
            storage_uri=storage_uri,
            strategy="fixed-window",
        )
        logger.info("rate_limiter.initialized", storage="redis", uri=storage_uri)
        return limiter
    except Exception as exc:
        logger.warning(
            "rate_limiter.redis_fallback",
            error=str(exc),
            storage="memory",
        )
        # Fallback to in-memory (no storage_uri)
        return Limiter(
            key_func=get_remote_address,
            strategy="fixed-window",
        )


# Module-level limiter instance (lazy-initialized)
_limiter: Limiter | None = None


def get_limiter() -> Limiter:
    """Get or create the global limiter instance."""
    global _limiter
    if _limiter is None:
        _limiter = _create_limiter()
    return _limiter


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Custom handler for 429 Too Many Requests.

    Returns a structured JSON error with Retry-After header.
    """
    logger.warning(
        "rate_limiter.exceeded",
        client_ip=get_remote_address(request),
        path=request.url.path,
        limit=str(exc.detail),
    )
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Too many requests. Please slow down.",
            "code": 429,
            "path": str(request.url.path),
        },
        headers={"Retry-After": "60"},
    )
