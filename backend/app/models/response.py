"""Pydantic response models for the AI assistant API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.places import FairnessAudit, PlaceDecisionTrace
from app.models.request import LatLng


class ScoreBreakdown(BaseModel):
    """Deterministic fairness re-ranking score components."""

    relevance: float = Field(description="Relevance score (0-1).")
    proximity: float = Field(description="Proximity score (0-1).")
    quality: float = Field(description="Quality score (0-1).")
    geo_locality: float = Field(description="Locality score based on coordinates (0-1).")
    popularity_damping: float = Field(description="Applied popularity damping penalty.")
    weights: dict[str, float] = Field(description="Weights applied to each component.")
    gate_passed: bool = Field(description="Whether the place passed the relevance/quality gate.")
    final_score: float = Field(description="Clipped final score, bounded to [0, 1].")
    rank: int = Field(description="1-based rank after stable sort by final_score descending.")


class AccessibilityInfo(BaseModel):
    """Accessibility metadata for a place."""

    has_wheelchair_access: bool = Field(
        description="Whether the venue has verified wheelchair access.",
    )
    warning: str | None = Field(
        default=None,
        description="Optional warning about accessibility limitations.",
    )


class PlaceExplanation(BaseModel):
    """Safe structured explanation for why a place was recommended."""

    model_config = ConfigDict(extra="forbid")

    rank: int = Field(default=0, ge=0, description="1-based recommendation rank, or 0 when not ranked.")
    primary_reason: str = Field(default="Recommended from grounded place data with limited metadata.", max_length=240, description="Concise reason derived only from normalized place fields.")
    matched_preferences: list[str] = Field(default_factory=list, max_length=10, description="Preference signals matched by the normalized candidate.")
    local_context: str = Field(default="local signal unknown", max_length=160, description="Safe locality/fairness context without exact user GPS.")
    score_factors: dict[str, float | int | str | None] = Field(default_factory=dict, max_length=12, description="Compact score fields used by the reranker or fallback scorer.")
    fairness_note: str = Field(default="local representation metadata limited", max_length=200, description="Fairness/locality note derived from local_factor metadata.")
    accessibility_note: str = Field(default="accessibility metadata unknown", max_length=200, description="Accessibility note derived from normalized accessibility fields.")
    route_summary: str = Field(default="route metadata unavailable", max_length=200, description="Route summary without exact origin/user GPS.")
    provider_source: str | None = Field(default=None, max_length=64, description="Normalized provider/source label when available.")
    provider_status: str | None = Field(default=None, max_length=64, description="Normalized provider status when available.")
    evidence_fields_used: list[str] = Field(default_factory=list, max_length=20, description="Normalized candidate/result fields used to build this explanation.")
    detail_highlights: list[str] = Field(default_factory=list, max_length=8, description="Human-friendly highlights derived from Place Details (New).")

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
                    "geo_locality": 1.0,
                    "final_score": 0.87,
                    "score_breakdown": {
                        "relevance": 0.90,
                        "proximity": 0.65,
                        "quality": 0.75,
                        "geo_locality": 1.0,
                        "popularity_damping": 0.045,
                        "weights": {"relevance": 0.40, "proximity": 0.25, "quality": 0.20, "geo_locality": 0.15},
                        "gate_passed": True,
                        "final_score": 0.87,
                        "rank": 1,
                    },
                    "accessibility_score": 0.75,
                    "map_uri": "https://map.goong.io/?pid=ChIJ123abc",
                }
            ]
        }
    )

    place_id: str = Field(description="Goong Places unique identifier.")
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
    primary_type_display_name: str | None = Field(
        default=None,
        description="Localized primary type label when available from Place Details.",
    )
    rating: float | None = Field(
        default=None,
        ge=0.0,
        le=5.0,
        description="Provider rating (0-5), or null if unrated.",
    )
    user_rating_count: int | None = Field(
        default=None,
        ge=0,
        description="Number of Provider user ratings, or null when unavailable.",
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
    current_opening_hours: dict | None = Field(default=None, description="Current opening hours from Place Details when available.")
    regular_opening_hours: dict | None = Field(default=None, description="Regular opening hours from Place Details when available.")
    payment_options: dict[str, bool] = Field(default_factory=dict, description="Accepted payment options from Place Details.")
    parking_options: dict[str, bool] = Field(default_factory=dict, description="Parking options from Place Details.")
    editorial_summary: str | None = Field(default=None, description="Provider editorial summary, presented as-is when available.")
    generative_summary: str | None = Field(default=None, description="Google AI-generated place summary when available.")
    review_summary: str | None = Field(default=None, description="Google AI-generated review summary when available.")
    reviews: list[dict] = Field(default_factory=list, description="Bounded provider reviews from Place Details.")
    photos: list[str] = Field(default_factory=list, description="Bounded provider photo resource names from Place Details.")
    service_options: dict[str, bool | None] = Field(default_factory=dict, description="Dining/service flags such as takeout, delivery, dine_in, reservable, serves_*.")
    geo_locality: float | None = Field(
        default=None,
        description="Locality signal based on location; null if unknown.",
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
    map_uri: str = Field(
        description="Deep link to open the place in a provider map.",
    )
    explanation: PlaceExplanation = Field(
        default_factory=PlaceExplanation,
        description="Structured why-this-recommendation data for the place.",
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
    threshold_results: dict = Field(
        default_factory=dict,
        description=(
            "Per-metric threshold check results. Each key maps to a dict with "
            "'score', 'threshold', and 'passed' fields."
        ),
    )
    all_passed: bool = Field(
        default=False,
        description=(
            "True when every evaluated metric meets or exceeds its threshold. "
            "False when any metric falls below threshold or no metrics were evaluated."
        ),
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
    recent_traces: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Recent trace summaries from Langfuse (trace_id, session_id, name, "
            "timestamp, latency_ms, total_cost). None when disabled or unavailable."
        ),
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


class AdminStatsResponse(BaseModel):
    """Response body for GET /admin/stats — corpus operational visibility."""

    total_chunks: int = Field(
        description="Number of chunks in the in-process retriever."
    )
    total_docs: int = Field(
        description="Number of unique source documents in the retriever."
    )
    language_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="Count of chunks per language code (e.g. {'vi': 607}).",
    )
    bm25_vocab_size: int = Field(
        default=0,
        description="Number of unique terms in the BM25 vectorizer vocabulary.",
    )
    hybrid_enabled: bool = Field(
        default=False,
        description="Whether hybrid retrieval (Qdrant + BM25) is active.",
    )
    qdrant_collection_name: str | None = Field(
        default=None,
        description="Active Qdrant collection name, or null if not configured.",
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
    suggestions: list[str] = Field(
        default_factory=list,
        description="Optional list of dynamic suggestion chips generated by the LLM.",
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
    fairness_audit: FairnessAudit | None = Field(
        default=None,
        description="Structured fairness audit snapshot for place recommendation calls.",
    )
    decision_trace: PlaceDecisionTrace | None = Field(
        default=None,
        description="R046 structured decision trace for the full search_places path.",
    )
