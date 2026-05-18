"""Request correlation ID middleware.

Generates or extracts an X-Request-ID header and binds it to structlog
context so every log line in a request's lifecycle includes the same
correlation ID. This makes it possible to trace a request through error
paths (422 validation, 502 proxy failure, 503 service unavailable) and
into downstream services.

The ID is also returned in the response header so clients can reference
it when reporting issues.
"""

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_HEADER = "x-request-id"
logger = structlog.get_logger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware that ensures every request has a correlation ID."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Extract or generate correlation ID
        correlation_id = request.headers.get(CORRELATION_HEADER)
        generated = False
        if not correlation_id:
            correlation_id = str(uuid.uuid4())
            generated = True

        # Bind to structlog context — all logs in this request will include it
        structlog.contextvars.bind_contextvars(request_id=correlation_id)

        try:
            response = await call_next(request)
            response.headers[CORRELATION_HEADER] = correlation_id
        finally:
            # Clear context vars to prevent leakage between requests
            structlog.contextvars.unbind_contextvars("request_id")

        if generated:
            logger.debug("correlation_id.generated", method=request.method, path=request.url.path)

        return response
