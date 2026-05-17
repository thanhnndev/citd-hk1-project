"""Authentication dependency scaffolding.

Placeholder verify_api_key dependency that always passes.  Real
implementation should validate against an API key store or JWT provider
before S04 rollout.
"""

from fastapi import Depends, Header, HTTPException, status


async def verify_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> bool:
    """Placeholder auth dependency — always returns True.

    TODO: Replace with real API key validation:
    1. Look up x_api_key in a secrets store (e.g. Redis or PostgreSQL).
    2. Validate JWT token for user-facing endpoints.
    3. Return HTTPException(401) on missing or invalid credentials.

    For now this allows all requests through so that downstream services
    can be developed without auth gating.
    """
    # TODO: Implement real API key / JWT validation before production.
    return True
