"""Application middleware package.

Provides CORS configuration, auth dependencies, and rate-limiting
placeholders wired into the FastAPI lifespan.
"""

from app.middleware.cors import create_cors_middleware
from app.middleware.auth import verify_api_key

__all__ = ["create_cors_middleware", "verify_api_key"]
