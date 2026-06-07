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


class PriceLevel(StrEnum):
    """Symbolic budget preference levels that map to Google/Goong price_level 0-4."""

    FREE = "free"
    INEXPENSIVE = "inexpensive"
    MODERATE = "moderate"
    EXPENSIVE = "expensive"
    VERY_EXPENSIVE = "very_expensive"


# Map symbolic budget names to numeric price_level values (0-4).
_PRICE_LEVEL_TO_NUMERIC: dict[str, list[int]] = {
    PriceLevel.FREE: [0],
    PriceLevel.INEXPENSIVE: [0, 1],
    PriceLevel.MODERATE: [0, 1, 2],
    PriceLevel.EXPENSIVE: [2, 3],
    PriceLevel.VERY_EXPENSIVE: [3, 4],
}


class PlaceSearchRequest(BaseModel):
    """Text search request normalized before reaching Goong Places.

    Preference fields (budget, accessibility, user-location) are explicit typed
    inputs so downstream services can safely shape provider requests or reranking
    without parsing raw user text.  See R043.
    """

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=160)
    language_code: Literal["vi", "en"] = "vi"
    location_bias: LatLng = Field(default_factory=lambda: HAM_NINH_CENTER.model_copy())
    radius_meters: int = Field(default=DEFAULT_SEARCH_RADIUS_METERS, ge=1, le=MAX_SEARCH_RADIUS_METERS)
    included_type: str | None = Field(default=None, min_length=1, max_length=80)
    max_result_count: int = Field(default=10, ge=1, le=20)

    # -- Preference contract (R043) --

    budget_filter: list[PriceLevel] | None = Field(
        default=None,
        min_length=1,
        max_length=5,
        description=(
            "Symbolic budget constraint (e.g. ['free','inexpensive']). "
            "Maps to numeric price_level 0-4 downstream. None = no price filtering. "
            "Empty list is rejected — use None for no constraint."
        ),
    )
    wheelchair_accessible_preference: bool | None = Field(
        default=None,
        description=(
            "When true, prefer wheelchair-accessible venues in ranking/reranking. "
            "None = no preference (provider default behaviour)."
        ),
    )
    user_location: LatLng | None = Field(
        default=None,
        description=(
            "User's current GPS coordinates for proximity scoring. "
            "When absent the service falls back to location_bias (Ham Ninh center default)."
        ),
    )

    @property
    def effective_origin(self) -> LatLng:
        """Return user_location if set, otherwise the default location_bias."""
        return self.user_location or self.location_bias

    @property
    def numeric_price_levels(self) -> list[int] | None:
        """Convert symbolic budget_filter to numeric price_level values for provider queries.

        Returns None when no budget constraint is set (meaning: accept all price levels).
        Deduplicates and sorts the result for stable provider behaviour.
        """
        if not self.budget_filter:
            return None
        numeric: set[int] = set()
        for level in self.budget_filter:
            numeric.update(_PRICE_LEVEL_TO_NUMERIC.get(level.value, []))
        return sorted(numeric)

    def preference_summary(self) -> dict[str, Any]:
        """Audit-friendly summary of preference flags without raw user PII.

        Returns a small dict safe for logger.info/reasoning_log:
        - budget_set: whether any budget constraint was provided
        - budget_count: number of symbolic price levels requested
        - wheelchair_accessible_preference: bool or None
        - has_user_location: whether user_location differs from default
        - effective_origin_rounded: lat/lng rounded to 2 decimals (no exact GPS)
        """
        return {
            "budget_set": self.budget_filter is not None,
            "budget_count": len(self.budget_filter) if self.budget_filter else 0,
            "wheelchair_accessible_preference": self.wheelchair_accessible_preference,
            "has_user_location": self.user_location is not None,
            "effective_origin_rounded": {
                "lat": round(self.effective_origin.lat, 2),
                "lng": round(self.effective_origin.lng, 2),
            },
        }


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
    primary_type_display_name: str | None = Field(default=None, max_length=120)
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
    regular_opening_hours: dict[str, Any] | None = Field(default=None, max_length=20)
    current_opening_hours: dict[str, Any] | None = Field(default=None, max_length=20)
    payment_options: dict[str, bool] = Field(default_factory=dict, max_length=20)
    parking_options: dict[str, bool] = Field(default_factory=dict, max_length=20)
    editorial_summary: str | None = Field(default=None, max_length=500)
    generative_summary: str | None = Field(default=None, max_length=800)
    review_summary: str | None = Field(default=None, max_length=800)
    reviews: list[dict[str, Any]] = Field(default_factory=list, max_length=5)
    photos: list[str] = Field(default_factory=list, max_length=10)
    takeout: bool | None = None
    delivery: bool | None = None
    dine_in: bool | None = None
    reservable: bool | None = None
    serves_breakfast: bool | None = None
    serves_lunch: bool | None = None
    serves_dinner: bool | None = None
    serves_beer: bool | None = None
    serves_wine: bool | None = None
    serves_vegetarian_food: bool | None = None
    accessibility_score: float | None = Field(default=None, ge=0.0, le=1.0)
    accessibility_warning: str | None = Field(default=None, max_length=240)
    geo_locality: float | None = Field(default=None, ge=0.0, le=1.0)
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
    MISSING_LOCAL_FACTOR_METADATA = "missing_geo_locality_metadata"
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
    top5_local_ratio: float = Field(default=0.0, ge=0.0, le=1.0, description="Fraction of top-5 results with geo_locality >= 0.5.")
    missing_geo_locality_count: int = Field(default=0, ge=0, description="Candidates missing geo_locality metadata.")
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


# -- R046 decision trace / audit event vocabulary (M013/S05-T02) --

class PlaceAuditPhase(StrEnum):
    """Canonical phase labels for search_places decision trace events."""

    REQUEST = "request"
    PROVIDER = "provider"
    CACHE = "cache"
    ROUTE = "route"
    FILTER = "filter"
    RERANK = "rerank"
    FAIRNESS = "fairness"
    COMPOSE = "compose"
    CREDENTIAL = "credential"


# Compact event names — machine-readable, consistent across all paths.
PLACE_AUDIT_EVENTS = frozenset({
    # Request phase
    "request_built",
    "invalid_request",
    # Provider phase
    "provider_called",
    "provider_ok",
    "provider_error",
    "provider_credentials_blocked",
    "provider_unavailable",
    # Cache phase
    "cache_hit",
    "cache_miss",
    "cache_stale",
    "cache_error",
    "cache_skip",
    # Route phase
    "route_enrichment_ok",
    "route_enrichment_fallback",
    # Filter phase
    "preference_filter_applied",
    "preference_filter_skipped",
    # Rerank phase
    "reranking_ensemble",
    "reranking_fallback",
    # Fairness phase
    "fairness_balanced",
    # Compose phase
    "composition_deterministic",
    # Credential phase
    "credential_live",
    "credential_blocked",
    "credential_unavailable",
})


class PlaceAuditEvent(BaseModel):
    """Single redacted audit event in the search_places decision trace.

    Compact, bounded, and machine-readable. No API keys, raw provider JSON,
    exact user_location, phone numbers, or document citations.
    """

    model_config = ConfigDict(extra="forbid")

    event: str = Field(..., max_length=64, description="Canonical event name from PLACE_AUDIT_EVENTS.")
    phase: PlaceAuditPhase = Field(..., description="Phase of the decision path where this event occurred.")
    detail: dict[str, Any] = Field(
        default_factory=dict,
        max_length=10,
        description="Compact, redacted context for this event (no secrets).",
    )
    elapsed_ms: float | None = Field(
        default=None,
        description="Milliseconds since request start when this event fired.",
    )

    @field_validator("event")
    @classmethod
    def validate_event(cls, value: str) -> str:
        if value not in PLACE_AUDIT_EVENTS:
            raise ValueError(
                f"Unknown audit event: {value}. "
                f"Allowed: {sorted(PLACE_AUDIT_EVENTS)}"
            )
        return value


class PlaceDecisionTrace(BaseModel):
    """Structured audit trace for a single search_places decision path.

    Attached to ChatResponse so a future agent can determine which phases ran,
    which degraded, and whether live provider, cache fallback, or
    credential-blocked path produced the response.
    """

    model_config = ConfigDict(extra="forbid")

    events: list[PlaceAuditEvent] = Field(
        default_factory=list,
        max_length=30,
        description="Ordered audit events from the decision path.",
    )
    session_id: str = Field(default="", max_length=128, description="Session correlation ID.")
    credential_status: str | None = Field(
        default=None,
        max_length=64,
        description="Final credential status: live, blocked, unavailable, or unknown.",
    )
    provider_source: str | None = Field(
        default=None,
        max_length=64,
        description="Final provider/source label: google_places, goong_places, cache, mock, none.",
    )

    @property
    def total_events(self) -> int:
        """Count of events (computed from the events list)."""
        return len(self.events)


# -- Google Places API (New) typed contract --

# Provider contract version — bump when field mask or normalization semantics change.
GOOGLE_PLACES_PROVIDER_CONTRACT_VERSION = "v2"

# Field mask covering every rich field consumed by normalize_place().
# Google Places API (New) requires explicit field masks for billing — fields not
# listed here are omitted from the response and cannot be normalized.
GOOGLE_PLACES_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.shortFormattedAddress,"
    "places.location,places.types,places.primaryType,places.primaryTypeDisplayName,"
    "places.rating,places.userRatingCount,places.priceLevel,"
    "places.currentOpeningHours,places.businessStatus,places.accessibilityOptions,"
    "places.googleMapsUri,places.websiteUri"
)

GOOGLE_PLACE_DETAILS_FIELD_MASK = (
    "id,displayName,formattedAddress,shortFormattedAddress,location,types,"
    "primaryType,primaryTypeDisplayName,rating,userRatingCount,priceLevel,"
    "regularOpeningHours,currentOpeningHours,currentSecondaryOpeningHours,regularSecondaryOpeningHours,"
    "businessStatus,accessibilityOptions,nationalPhoneNumber,internationalPhoneNumber,"
    "googleMapsUri,websiteUri,editorialSummary,generativeSummary,reviewSummary,reviews,photos,"
    "paymentOptions,parkingOptions,takeout,delivery,dineIn,reservable,"
    "servesBreakfast,servesLunch,servesDinner,servesBeer,servesWine,servesVegetarianFood"
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
    interpreted_query: str | None = Field(
        default=None,
        max_length=160,
        description="Provider-ready query text after safe request interpretation; no API keys or raw payloads.",
    )
    request_metadata: dict[str, Any] = Field(
        default_factory=dict,
        max_length=20,
        description="Safe request-shaping metadata such as endpoint, field mask, locale, and result limits.",
    )
    candidates: list[PlaceCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, max_length=10, description="User-safe warning messages.")
    reasoning_log: list[str] = Field(default_factory=list, max_length=50, description="Step-by-step reasoning entries (no secrets).")
    explanation: str | None = Field(default=None, max_length=500, description="Human-readable explanation of the result.")
    place_recommendation_status: PlaceRecommendationStatus = Field(default_factory=PlaceRecommendationStatus)
    audit: dict[str, Any] = Field(default_factory=dict, max_length=30, description="Audit trail with no secrets or raw payloads.")
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
