"""Structured logging configuration via structlog.

Provides a setup_logging() function that configures JSON output for
production (or pretty output in development) and wires structlog into
Python's standard logging module.
"""

from typing import Any

import logging
import sys

import structlog
from structlog.contextvars import merge_contextvars
from structlog.dev import ConsoleRenderer
from structlog.processors import JSONRenderer, TimeStamper, add_log_level


def setup_logging(
    *,
    log_level: str = "INFO",
    json_logs: bool = True,
) -> None:
    """Configure structlog for the application.

    Args:
        log_level: Root logging level (e.g. "INFO", "DEBUG").
        json_logs: If True, emit JSON lines; otherwise use console rendering.
    """
    # Standard logging configuration
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    # Shared processors applied to every log event
    shared_processors: list = [
        merge_contextvars,
        add_log_level,
        TimeStamper(fmt="iso"),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            JSONRenderer() if json_logs else ConsoleRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    """Return a structlog logger instance.

    Args:
        name: Optional logger name (maps to __name__ in calling modules).

    Returns:
        A structlog bound logger ready for info/warning/error calls.
    """
    return structlog.get_logger(name)
