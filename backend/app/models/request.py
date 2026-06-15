"""Pydantic request models for the AI assistant API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LatLng(BaseModel):
    """Geographic coordinates for user location filtering."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"lat": 21.0285, "lng": 105.8542}]
        }
    )

    lat: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Latitude in decimal degrees.",
    )
    lng: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="Longitude in decimal degrees.",
    )


class ChatRequest(BaseModel):
    """
    Request body for the chat endpoint.

    The user submits a natural-language message along with optional context
    (location, budget, accessibility needs) that the LLM uses to score and
    rank place recommendations.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "session_id": "sess-abc-123",
                    "message": "Find affordable seafood restaurants near me",
                    "language": "vi",
                    "budget_filter": "low",
                    "user_location": {"lat": 10.0, "lng": 106.6},
                    "accessibility_required": True,
                }
            ]
        }
    )

    session_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Opaque session identifier for conversation continuity.",
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The user's natural-language query.",
    )
    language: Literal["vi", "en"] = Field(
        default="vi",
        description="Preferred response language (Vietnamese or English).",
    )
    budget_filter: str | None = Field(
        default=None,
        max_length=64,
        description="Optional budget constraint (e.g. 'low', 'medium', 'high').",
    )
    user_location: LatLng | None = Field(
        default=None,
        description="User's current GPS coordinates for proximity scoring.",
    )
    accessibility_required: bool = Field(
        default=False,
        description="When true, require provider-verified wheelchair entrance access.",
    )
