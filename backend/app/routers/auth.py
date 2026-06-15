"""Authentication endpoints — register, login, verify email, and profile.

Provides simple email/password auth with JWT tokens.
Email verification is controlled by the REQUIRE_EMAIL_VERIFICATION flag.
When enabled, a 6-digit OTP is sent to the user's email on registration.
"""

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from app.core.config import get_settings
from app.models.user import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.jwt_service import create_access_token

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Additional request models for verification ──────────────────────────

class VerifyEmailRequest(BaseModel):
    """Request body for email OTP verification."""
    email: EmailStr = Field(..., description="Email to verify.")
    otp: str = Field(..., min_length=6, max_length=6, description="6-digit OTP code.")


class ResendOTPRequest(BaseModel):
    """Request body to resend verification OTP."""
    email: EmailStr = Field(..., description="Email to resend OTP to.")


# ── Endpoints ───────────────────────────────────────────────────────────

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, request: Request) -> UserResponse:
    """Register a new user account.

    Creates a user with username, email, and hashed password.
    If REQUIRE_EMAIL_VERIFICATION is enabled, sends a 6-digit OTP
    to the user's email for verification.
    """
    user_service = getattr(request.app.state, "user_service", None)
    if user_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User service is not available.",
        )

    try:
        user = await user_service.register(
            username=body.username,
            email=body.email,
            password=body.password,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    # Send verification email if enabled
    settings = get_settings()
    if settings.REQUIRE_EMAIL_VERIFICATION:
        from app.services.email_service import generate_otp, otp_store, send_verification_email

        otp = generate_otp()
        otp_store.save(user.email, otp)
        sent = send_verification_email(to_email=user.email, otp=otp, username=user.username)
        if not sent:
            logger.warning("auth.otp_send_failed", email=user.email)

    logger.info("auth.register", username=user.username, email=user.email)

    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        is_verified=user.is_verified,
        is_admin=user.is_admin,
        created_at=user.created_at,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request) -> TokenResponse:
    """Authenticate and return a JWT access token.

    If REQUIRE_EMAIL_VERIFICATION is enabled, unverified users
    will receive a 403 Forbidden response.
    """
    user_service = getattr(request.app.state, "user_service", None)
    if user_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User service is not available.",
        )

    user = await user_service.authenticate(email=body.email, password=body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    # Check email verification if required
    settings = get_settings()
    if settings.REQUIRE_EMAIL_VERIFICATION and not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please verify your email before logging in.",
        )

    token = create_access_token(user_id=user.id, email=user.email)
    logger.info("auth.login", user_id=user.id, email=user.email)

    return TokenResponse(access_token=token)


@router.post("/verify-email")
async def verify_email(body: VerifyEmailRequest, request: Request) -> dict:
    """Verify a user's email with the 6-digit OTP code.

    After successful verification, the user's is_verified flag is set to True.
    """
    from app.services.email_service import otp_store

    user_service = getattr(request.app.state, "user_service", None)
    if user_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User service is not available.",
        )

    # Verify OTP
    is_valid = otp_store.verify(body.email, body.otp)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OTP code.",
        )

    # Mark user as verified
    await user_service.verify_email(body.email)
    logger.info("auth.email_verified", email=body.email)

    return {"message": "Email verified successfully.", "verified": True}


@router.post("/resend-otp")
async def resend_otp(body: ResendOTPRequest, request: Request) -> dict:
    """Resend the verification OTP to the user's email.

    Only works if REQUIRE_EMAIL_VERIFICATION is enabled and the user
    is not yet verified.
    """
    from app.services.email_service import generate_otp, otp_store, send_verification_email

    settings = get_settings()
    if not settings.REQUIRE_EMAIL_VERIFICATION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email verification is not enabled.",
        )

    user_service = getattr(request.app.state, "user_service", None)
    if user_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User service is not available.",
        )

    user = await user_service.get_by_email(body.email)
    if user is None:
        # Don't reveal whether email exists
        return {"message": "If the email is registered, a new OTP has been sent."}

    if user.is_verified:
        return {"message": "Email is already verified."}

    otp = generate_otp()
    otp_store.save(user.email, otp)
    sent = send_verification_email(to_email=user.email, otp=otp, username=user.username)

    if not sent:
        logger.warning("auth.resend_otp_failed", email=user.email)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification email. Please try again later.",
        )

    logger.info("auth.otp_resent", email=user.email)
    return {"message": "If the email is registered, a new OTP has been sent."}


@router.get("/me", response_model=UserResponse)
async def me(request: Request) -> UserResponse:
    """Get the current authenticated user's profile.

    Requires a valid JWT token in the Authorization header.
    """
    from app.middleware.auth import get_current_user

    user = await get_current_user(request)

    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        is_verified=user.is_verified,
        is_admin=user.is_admin,
        created_at=user.created_at,
    )
