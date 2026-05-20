"""Application middleware package.

Provides CORS configuration, JWT auth dependencies, rate limiting,
and correlation ID tracking wired into the FastAPI lifespan.
"""

from app.middleware.cors import create_cors_middleware
from app.middleware.auth import verify_api_key, get_current_user
from app.middleware.rate_limiter import get_limiter, rate_limit_exceeded_handler

__all__ = [
    "create_cors_middleware",
    "verify_api_key",
    "get_current_user",
    "get_limiter",
    "rate_limit_exceeded_handler",
]
