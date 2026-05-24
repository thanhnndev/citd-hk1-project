"""Pydantic response models for the AI assistant API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.request import LatLng


class ScoreBreakdown(BaseModel):
    """Ensemble scoring components for the 3-tree reranker pipeline.

    Replaces the legacy 5-field schema (relevance, proximity, price, rating,
    accessibility) with the ensemble schema defined in REQUIREMENTS.md §7.8.
    """

    tree1_locality: float = Field(
        description="Tree 1 locality-first score (0-1).",
    )
    tree2_proximity: float = Field(
        description="Tree 2 proximity-first score (0-1).",
    )
    tree3_quality: float = Field(
        description="Tree 3 quality-first score (0-1).",
    )
    s_bag: float = Field(
        description="Bagged average of the 3 tree scores (0-1).",
    )
    delta1_fairness: float = Field(
        description="Applied fairness correction: η × Δ1 (can be negative).",
    )
    delta2_access: float = Field(
        description="Applied accessibility correction: η × Δ2.",
    )
    final_score: float = Field(
        description="Clipped final score F2, bounded to [0, 1].",
    )
    rank: int = Field(
        description="1-based rank after stable sort by final_score descending.",
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
                    "location": {"lat": 10.1794, "lng": 104.0491},
                    "types": ["restaurant", "seafood_restaurant"],
                    "primary_type": "seafood_restaurant",
                    "rating": 4.5,
                    "user_rating_count": 128,
                    "price_level": 2,
                    "open_now": True,
                    "business_status": "OPERATIONAL",
                    "local_factor": 0.8,
                    "final_score": 0.87,
                    "score_breakdown": {
                        "tree1_locality": 0.90,
                        "tree2_proximity": 0.65,
                        "tree3_quality": 0.75,
                        "s_bag": 0.767,
                        "delta1_fairness": -0.045,
                        "delta2_access": 0.0,
                        "final_score": 0.72,
                        "rank": 1,
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
    location: LatLng | None = Field(
        default=None,
        description="Exact provider-supplied coordinates, or null when unavailable.",
    )
    types: list[str] = Field(
        default_factory=list,
        description="Provider-supplied place type tags for filtering and display.",
    )
    primary_type: str | None = Field(
        default=None,
        description="Provider-supplied primary place type when available.",
    )
    rating: float | None = Field(
        default=None,
        ge=0.0,
        le=5.0,
        description="Google Maps rating (0-5), or null if unrated.",
    )
    user_rating_count: int | None = Field(
        default=None,
        ge=0,
        description="Number of Google Maps user ratings, or null when unavailable.",
    )
    price_level: int | None = Field(
        default=None,
        ge=0,
        le=4,
        description="Price level from 0 (free) to 4 (very expensive), or null.",
    )
    open_now: bool | None = Field(
        default=None,
        description="Whether the venue is currently open, or null when unknown.",
    )
    business_status: str | None = Field(
        default=None,
        description="Provider-supplied business status when available.",
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


class EmbedResponse(BaseModel):
    """Response body for the POST /admin/embed endpoint."""

    total_docs: int = Field(description="Number of source documents in corpus")
    total_chunks: int = Field(
        description="Number of chunks indexed into Qdrant (propositions for proposition corpus)"
    )
    propositions_ingested: int = Field(
        description="Number of proposition chunks ingested (same as total_chunks for proposition corpus)"
    )
    language_distribution: dict[str, int] = Field(
        description="Count of chunks per language code (e.g. {'vi': 607})"
    )
    vector_dim: int = Field(description="Embedding vector dimension")
    collection_name: str = Field(description="Qdrant collection name")
    latency_ms: float = Field(description="Total embed+upsert latency in milliseconds")


class EvalTriggerRequest(BaseModel):
    """Request body for POST /admin/eval/trigger."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "dataset_path": "data/eval_dataset.jsonl",
                    "metrics": ["faithfulness", "answer_relevancy"],
                }
            ]
        }
    )

    dataset_path: str | None = Field(
        default=None,
        description="Path to eval dataset JSONL. Defaults to data/eval_dataset.jsonl.",
    )
    metrics: list[str] | None = Field(
        default=None,
        description="Metric names to compute. Defaults to all four.",
    )


class EvalResultResponse(BaseModel):
    """Response body for evaluation results."""

    verdict: str = Field(
        description="Evaluation verdict: completed, credential_blocked, or failed.",
    )
    metrics: dict = Field(
        default_factory=dict,
        description="Evaluation metrics dict (empty when blocked).",
    )
    timestamp: str = Field(
        description="ISO-8601 timestamp of the evaluation.",
    )
    dataset_size: int = Field(
        default=0,
        description="Number of questions evaluated.",
    )
    latency_ms: float = Field(
        default=0.0,
        description="Evaluation latency in milliseconds.",
    )
    result_path: str | None = Field(
        default=None,
        description="Filesystem path to the persisted result JSON.",
    )


class EvalFileListing(BaseModel):
    """Single entry in GET /admin/eval/results response."""

    filename: str = Field(description="Result filename.")
    timestamp: str = Field(description="ISO-8601 timestamp from result content.")
    verdict: str = Field(description="Evaluation verdict.")
    dataset_size: int = Field(description="Number of questions evaluated.")


class TracesStatusResponse(BaseModel):
    """Response body for GET /admin/traces."""

    langfuse_enabled: bool = Field(
        description="Whether Langfuse tracing is active.",
    )
    host: str | None = Field(
        default=None,
        description="Langfuse host URL when enabled.",
    )
    message: str = Field(
        description="Human-readable status message.",
    )


class FairnessSummaryResponse(BaseModel):
    """Response body for GET /admin/fairness."""

    total_audits: int = Field(
        description="Total number of fairness audit snapshots on disk.",
    )
    latest_timestamp: str | None = Field(
        default=None,
        description="ISO-8601 timestamp of the most recent audit entry.",
    )
    local_factor_distribution: dict | None = Field(
        default=None,
        description="Aggregated distribution with buckets, mean, and count.",
    )
    message: str | None = Field(
        default=None,
        description="Human-readable message when no audits exist.",
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
    fallback: bool = Field(
        default=False,
        description=(
            "True when the LLM call failed and the response was composed "
            "by the deterministic fallback path."
        ),
    )
    guardrail_status: str | None = Field(
        default=None,
        description=(
            "Guardrail verdict: 'pass', 'input_blocked', 'off_topic', "
            "or 'output_flagged'. None when guardrails are not evaluated."
        ),
    )
    guardrail_reason: str | None = Field(
        default=None,
        description="Human-readable reason for the guardrail verdict.",
    )
