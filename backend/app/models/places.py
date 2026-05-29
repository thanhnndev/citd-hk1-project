"""Contracts for mockable Goong Places API tool calls and normalized results."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.request import LatLng

HAM_NINH_CENTER = LatLng(lat=10.1835208, lng=104.0496843)
DEFAULT_SEARCH_RADIUS_METERS = 5_000
MAX_SEARCH_RADIUS_METERS = 50_000


class PlaceToolStatus(StrEnum):
    """Safe status envelope for Places tool responses."""

    OK = "ok"
    EMPTY = "empty"
    CREDENTIALS_BLOCKED = "credentials_blocked"
    UPSTREAM_ERROR = "upstream_error"
    INVALID_REQUEST = "invalid_request"


class PlaceToolSource(StrEnum):
    """Inspectable source of the returned place candidates."""

    GOONG_PLACES = "goong_places"
    MOCK = "mock"
    CACHE = "cache"


class PlaceToolError(BaseModel):
    """Sanitized error details safe for public response envelopes."""

    code: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=240)
    retryable: bool = False


class RouteContext(BaseModel):
    """Placeholder for later route-aware ranking without depending on Routes yet."""

    origin: LatLng | None = None
    travel_mode: Literal["walk", "drive", "bicycle", "transit"] | None = None
    distance_meters: int | None = Field(default=None, ge=0)
    duration_seconds: int | None = Field(default=None, ge=0)


class PlaceSearchRequest(BaseModel):
    """Text search request normalized before reaching Goong Places."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=160)
    language_code: Literal["vi", "en"] = "vi"
    location_bias: LatLng = Field(default_factory=lambda: HAM_NINH_CENTER.model_copy())
    radius_meters: int = Field(default=DEFAULT_SEARCH_RADIUS_METERS, ge=1, le=MAX_SEARCH_RADIUS_METERS)
    included_type: str | None = Field(default=None, min_length=1, max_length=80)
    max_result_count: int = Field(default=10, ge=1, le=20)


class PlaceNearbyRequest(BaseModel):
    """Nearby search request constrained to safe public inputs."""

    model_config = ConfigDict(extra="forbid")

    center: LatLng = Field(default_factory=lambda: HAM_NINH_CENTER.model_copy())
    radius_meters: int = Field(default=DEFAULT_SEARCH_RADIUS_METERS, ge=1, le=MAX_SEARCH_RADIUS_METERS)
    included_type: str = Field(..., min_length=1, max_length=80)
    language_code: Literal["vi", "en"] = "vi"
    max_result_count: int = Field(default=10, ge=1, le=20)


class PlaceDetailsRequest(BaseModel):
    """Details lookup request by Goong place id."""

    model_config = ConfigDict(extra="forbid")

    place_id: str = Field(..., min_length=1, max_length=256)
    language_code: Literal["vi", "en"] = "vi"


class PlaceCandidate(BaseModel):
    """Normalized, fairness-ready place candidate returned by the Places tool."""

    model_config = ConfigDict(extra="forbid")

    place_id: str = Field(..., min_length=1, max_length=256)
    resource_name: str | None = Field(default=None, max_length=256)
    display_name: str = Field(..., min_length=1, max_length=200)
    types: list[str] = Field(default_factory=list, max_length=30)
    formatted_address: str | None = Field(default=None, max_length=500)
    short_formatted_address: str | None = Field(default=None, max_length=240)
    location: LatLng | None = None
    primary_type: str | None = Field(default=None, max_length=80)
    rating: float | None = Field(default=None, ge=0.0, le=5.0)
    user_rating_count: int | None = Field(default=None, ge=0)
    price_level: int | None = Field(default=None, ge=0, le=4)
    open_now: bool | None = None
    business_status: str | None = Field(default=None, max_length=80)
    accessibility_options: dict[str, bool] = Field(default_factory=dict, max_length=20)
    national_phone_number: str | None = Field(default=None, max_length=80)
    international_phone_number: str | None = Field(default=None, max_length=80)
    map_uri: str | None = Field(default=None, max_length=2048)
    website_uri: str | None = Field(default=None, max_length=2048)
    accessibility_score: float | None = Field(default=None, ge=0.0, le=1.0)
    accessibility_warning: str | None = Field(default=None, max_length=240)
    local_factor: float | None = Field(default=None, ge=0.0, le=1.0)
    fairness_tags: list[str] = Field(default_factory=list, max_length=20)
    route_context: RouteContext | None = None

    @field_validator("fairness_tags")
    @classmethod
    def validate_fairness_tags(cls, value: list[str]) -> list[str]:
        for tag in value:
            if not tag or len(tag) > 64:
                raise ValueError("fairness tags must be 1-64 characters")
        return value


class PlaceToolResponse(BaseModel):
    """Public Places tool envelope with safe diagnostics and no raw provider payload."""

    model_config = ConfigDict(extra="forbid")

    status: PlaceToolStatus
    source: PlaceToolSource
    candidates: list[PlaceCandidate] = Field(default_factory=list)
    request: PlaceSearchRequest | PlaceNearbyRequest | PlaceDetailsRequest
    retrieved_at: datetime
    error: PlaceToolError | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, max_length=20)
