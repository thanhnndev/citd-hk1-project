"""Langfuse observability service.

Initializes the Langfuse Python client from application settings for
tracing LLM calls, agent runs, and RAG pipelines.  Gracefully skips
initialization when API keys are absent (development mode).
"""

from collections.abc import Callable
from typing import Any

import structlog

from app.core.config import Settings

logger = structlog.get_logger(__name__)


def init_langfuse(
    settings: Settings,
) -> tuple[Callable[[], None] | None, Any | None]:
    """Create and configure a Langfuse client, returning (cleanup_fn, client).

    Args:
        settings: Application settings containing LANGFUSE_* variables.

    Returns:
        A tuple of (shutdown_callback, langfuse_client). Both are None
        if Langfuse is disabled (missing API keys or import error).
    """
    public_key = settings.LANGFUSE_PUBLIC_KEY
    secret_key = settings.LANGFUSE_SECRET_KEY

    if not public_key or not secret_key:
        logger.warning(
            "langfuse.disabled",
            reason="LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY not set",
        )
        return (None, None)

    try:
        from langfuse import Langfuse  # type: ignore[import-untyped]

        client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=settings.LANGFUSE_HOST,
        )

        # Verify connectivity at startup
        client.auth_check()
        logger.info(
            "langfuse.connected",
            host=settings.LANGFUSE_HOST,
        )

        def _cleanup() -> None:
            """Flush pending events and close the Langfuse client."""
            try:
                client.flush()
                client.shutdown()
                logger.info("langfuse.shutdown")
            except Exception:
                logger.exception("langfuse.cleanup_failed")

        return (_cleanup, client)

    except ImportError:
        logger.warning(
            "langfuse.disabled",
            reason="langfuse package not installed",
        )
        return (None, None)
    except Exception:
        logger.exception("langfuse.init_failed")
        return (None, None)
