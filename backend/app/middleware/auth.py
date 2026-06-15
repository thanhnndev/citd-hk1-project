"""Authentication middleware — JWT-based user verification.

Provides two dependencies:
- get_current_user(): Strict — requires valid JWT, returns UserRecord.
- verify_api_key(): Lenient — allows requests through in dev mode if no token.

The REQUIRE_EMAIL_VERIFICATION flag controls whether unverified users
can access protected endpoints.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.services.jwt_service import decode_access_token


async def get_current_user(request: Request):
    """Extract and validate JWT from Authorization header.

    Returns:
        UserRecord from the database.

    Raises:
        HTTPException 401 if token is missing, invalid, or user not found.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Look up user in database
    user_service = getattr(request.app.state, "user_service", None)
    if user_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User service unavailable.",
        )

    user = await user_service.get_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )

    return user


async def get_current_admin(user=Depends(get_current_user)):
    """Require an authenticated user with admin privileges."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return user


async def verify_api_key(request: Request) -> bool:
    """Lenient auth dependency for chat/admin endpoints.

    Behavior:
    - If Authorization header is present → validate JWT (strict).
    - If no header and APP_ENV=development → allow through (dev convenience).
    - Otherwise → 401.

    This preserves backward compatibility while adding real auth.
    """
    from app.core.config import get_settings

    auth_header = request.headers.get("Authorization")

    # No auth header — check if dev mode allows bypass
    if not auth_header:
        settings = get_settings()
        if settings.APP_ENV == "development":
            return True
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Has auth header — validate JWT
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Use: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True
