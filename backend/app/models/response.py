"""Pydantic response models for the AI assistant API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ScoreBreakdown(BaseModel):
    """Individual scoring components for a recommended place."""

    relevance: float = Field(
        description="How well the place matches the user's intent (0-1)."
    )
    proximity: float = Field(
        description="Normalized distance score relative to user location (0-1)."
    )
    price: float = Field(
        description="Price alignment score with user budget (0-1)."
    )
    rating: float = Field(
        description="Normalized Google Maps rating score (0-1)."
    )
    accessibility: float = Field(
        description="Accessibility compliance score (0-1)."
    )


class AccessibilityInfo(BaseModel):
    """Accessibility metadata for a place."""

    has_wheelchair_access: bool = Field(
        description="Whether the venue has verified wheelchair access.",
    )
    warning: str | None = Field(
        default=None,
        description="Optional warning about accessibility limitations.",
    )


class PlaceResult(BaseModel):
    """
    A single place recommendation with full scoring details.

    Each place is ranked by a composite final_score that weighs relevance,
    proximity, price fit, quality rating, and accessibility.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "place_id": "ChIJ123abc",
                    "display_name": "Nhà hàng Biển Xanh",
                    "formatted_address": "123 Đường Biển, Phú Quốc, Kiên Giang",
                    "rating": 4.5,
                    "price_level": 2,
                    "local_factor": 0.8,
                    "final_score": 0.87,
                    "score_breakdown": {
                        "relevance": 0.95,
                        "proximity": 0.80,
                        "price": 0.90,
                        "rating": 0.85,
                        "accessibility": 0.75,
                    },
                    "accessibility_score": 0.75,
                    "google_maps_uri": "https://maps.google.com/?q=ChIJ123abc",
                }
            ]
        }
    )

    place_id: str = Field(description="Google Places unique identifier.")
    display_name: str = Field(description="Human-readable name of the place.")
    formatted_address: str | None = Field(
        default=None,
        description="Full street address when available.",
    )
    rating: float | None = Field(
        default=None,
        ge=0.0,
        le=5.0,
        description="Google Maps rating (0-5), or null if unrated.",
    )
    price_level: int | None = Field(
        default=None,
        ge=0,
        le=4,
        description="Price level from 0 (free) to 4 (very expensive), or null.",
    )
    local_factor: float = Field(
        description="Locality signal — higher for locally-owned businesses.",
    )
    final_score: float = Field(
        description="Composite ranking score used for sorting results (0-1)."
    )
    score_breakdown: ScoreBreakdown = Field(
        description="Individual component scores that compose final_score.",
    )
    accessibility_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Normalized accessibility score, or null if unknown.",
    )
    accessibility_warning: str | None = Field(
        default=None,
        description="Specific accessibility caveat if known.",
    )
    google_maps_uri: str = Field(
        description="Deep link to open the place in Google Maps.",
    )


class Citation(BaseModel):
    """A source citation attached to an AI-generated response."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "source": "Vietnam Tourism Board",
                    "url": "https://vietnam.travel/phu-quoc",
                    "snippet": "Phu Quoc offers a range of dining options...",
                }
            ]
        }
    )

    source: str = Field(description="Name of the cited source.")
    url: str | None = Field(
        default=None,
        description="Direct URL to the source material.",
    )
    snippet: str | None = Field(
        default=None,
        description="Brief excerpt from the source.",
    )


class ChatResponse(BaseModel):
    """
    Response body for the chat endpoint.

    Contains the LLM-generated reply, an ordered list of recommended places,
    source citations for transparency, and optional observability fields.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "session_id": "sess-abc-123",
                    "message": "Dưới đây là 3 nhà hàng hải sản giá tốt gần bạn...",
                    "citations": [],
                    "places": [],
                    "reasoning_log": None,
                    "intent": "restaurant_search",
                    "langfuse_trace_id": None,
                    "latency_ms": 342.5,
                }
            ]
        }
    )

    session_id: str = Field(
        description="Echoed session identifier for client correlation.",
    )
    message: str = Field(
        description="The AI assistant's natural-language response.",
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description="Source citations backing the response.",
    )
    places: list[PlaceResult] = Field(
        default_factory=list,
        description="Ordered list of place recommendations.",
    )
    reasoning_log: str | None = Field(
        default=None,
        description="Optional internal reasoning summary for debugging.",
    )
    intent: str | None = Field(
        default=None,
        description="Detected user intent category (e.g. 'restaurant_search').",
    )
    langfuse_trace_id: str | None = Field(
        default=None,
        description="Langfuse trace ID for distributed tracing.",
    )
    latency_ms: float = Field(
        description="Total response latency in milliseconds.",
    )
