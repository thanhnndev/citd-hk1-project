"""CORS middleware factory.

Returns a Starlette CORSMiddleware configured with the project's allowed
origins from settings.  Credentials and all HTTP methods/headers are
permitted to support the SPA frontend development workflow.
"""

from starlette.middleware.cors import CORSMiddleware


def create_cors_middleware(origins: list[str]) -> CORSMiddleware:
    """Build a CORSMiddleware instance for the given allowed origins.

    Args:
        origins: List of allowed origin URLs (e.g. from settings.CORS_ORIGINS).

    Returns:
        A CORSMiddleware configured to accept credentials and all methods/headers.
    """
    return CORSMiddleware(
        app=None,  # Attached by FastAPI via app.add_middleware()
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
