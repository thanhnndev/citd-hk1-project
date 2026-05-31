"""Contracts for mockable Goong Places API tool calls and normalized results."""

from __future__ import annotations

from datetime import UTC, datetime
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
    UNAVAILABLE = "unavailable"


class PlaceToolSource(StrEnum):
    """Inspectable source of the returned place candidates."""

    GOOGLE_PLACES = "google_places"
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


# -- Fairness audit contract (M013/S02) --

class FairnessWarningType(StrEnum):
    """Standardized warning vocabulary for fairness audit diagnostics."""

    INSUFFICIENT_LOCAL_CANDIDATES = "insufficient_local_candidates"
    MISSING_LOCAL_FACTOR_METADATA = "missing_local_factor_metadata"
    PROVIDER_NON_OK = "provider_non_ok"
    ROUTE_ENRICHMENT_FALLBACK = "route_enrichment_fallback"
    ENSEMBLE_FALLBACK = "ensemble_fallback"


class FairnessAudit(BaseModel):
    """Structured fairness audit snapshot attached to every recommendation call.

    Captures: candidate/result counts, top-5 local representation ratio,
    missing metadata count, provider status, and user-safe warnings.
    Redaction guarantee: no API keys, raw provider payloads, or user PII.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_count: int = Field(default=0, ge=0, description="Total candidate pool size.")
    result_count: int = Field(default=0, ge=0, description="Number of results returned.")
    top5_local_ratio: float = Field(default=0.0, ge=0.0, le=1.0, description="Fraction of top-5 results with local_factor >= 0.5.")
    missing_local_factor_count: int = Field(default=0, ge=0, description="Candidates missing local_factor metadata.")
    provider_status: str = Field(default="unknown", max_length=64, description="Safe provider status value (e.g. ok, empty, upstream_error).")
    warnings: list[str] = Field(default_factory=list, max_length=10, description="User-safe fairness warning messages.")

    @field_validator("warnings")
    @classmethod
    def validate_warnings(cls, value: list[str]) -> list[str]:
        allowed = {w.value for w in FairnessWarningType}
        for w in value:
            if w not in allowed:
                raise ValueError(f"Unknown fairness warning: {w}. Allowed: {sorted(allowed)}")
        return value


# -- Google Places API (New) typed contract --

GOOGLE_PLACES_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.location,"
    "places.rating,places.priceLevel,places.accessibilityOptions,"
    "places.businessStatus"
)


class ProviderStatus(BaseModel):
    """Sanitized provider response metadata with no secrets or raw payloads."""

    model_config = ConfigDict(extra="forbid")

    http_status: int | None = Field(default=None, description="Provider HTTP status code when available.")
    provider_code: str | None = Field(default=None, max_length=64, description="Provider-specific status code (e.g. REQUEST_DENIED).")
    provider_message: str | None = Field(default=None, max_length=500, description="Sanitized provider error message with no secrets.")
    request_id: str | None = Field(default=None, max_length=128, description="Provider request ID for correlation, if present.")


class PlaceRecommendationStatus(BaseModel):
    """Structured diagnostics for why places were or were not recommended."""

    model_config = ConfigDict(extra="forbid")

    provider_places_returned: int = Field(default=0, ge=0, description="Number of raw places returned by the provider.")
    candidates_after_normalization: int = Field(default=0, ge=0, description="Number of candidates surviving normalization.")
    filters_applied: list[str] = Field(default_factory=list, max_length=20, description="Filters applied (e.g. max_result_count, included_type).")
    reason: str | None = Field(default=None, max_length=500, description="Human-readable explanation of recommendation outcome.")


class SearchPlacesToolResult(BaseModel):
    """Typed tool result for /chat place-discovery backed by Google Places API (New).

    Provides: status/provider_status/source/warnings/reasoning_log/audit fields,
    structured place_recommendation_status diagnostics, extra='forbid',
    safe credential-blocked/upstream status metadata, and no raw provider payload leakage.
    """

    model_config = ConfigDict(extra="forbid")

    status: PlaceToolStatus
    source: PlaceToolSource
    provider_status: ProviderStatus = Field(default_factory=ProviderStatus)
    candidates: list[PlaceCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, max_length=10, description="User-safe warning messages.")
    reasoning_log: list[str] = Field(default_factory=list, max_length=50, description="Step-by-step reasoning entries (no secrets).")
    explanation: str | None = Field(default=None, max_length=500, description="Human-readable explanation of the result.")
    place_recommendation_status: PlaceRecommendationStatus = Field(default_factory=PlaceRecommendationStatus)
    audit: dict[str, Any] = Field(default_factory=dict, max_length=30, description="Audit trail with no secrets or raw payloads.")
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
