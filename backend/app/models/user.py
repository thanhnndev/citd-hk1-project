"""Pydantic models for user authentication."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    """Request body for user registration."""

    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Unique username.",
    )
    email: EmailStr = Field(
        ...,
        description="User email address.",
    )
    password: str = Field(
        ...,
        min_length=6,
        max_length=128,
        description="Plain-text password (will be hashed server-side).",
    )


class LoginRequest(BaseModel):
    """Request body for user login."""

    email: EmailStr = Field(..., description="Registered email address.")
    password: str = Field(..., description="Plain-text password.")


class TokenResponse(BaseModel):
    """JWT token response after successful login."""

    access_token: str = Field(description="JWT access token.")
    token_type: str = Field(default="bearer", description="Token type.")


class UserResponse(BaseModel):
    """Public user profile returned by /auth/me."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="User UUID.")
    username: str = Field(description="Username.")
    email: str = Field(description="Email address.")
    is_active: bool = Field(description="Whether the account is active.")
    is_verified: bool = Field(description="Whether the email is verified.")
    is_admin: bool = Field(description="Whether the user can access admin features.")
    created_at: datetime = Field(description="Account creation timestamp.")
