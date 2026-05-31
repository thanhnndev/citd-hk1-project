# M014/S03 Recommendation Explanation Contract

**Status:** Verified (local contract)
**Date:** 2025-05-30
**Verifier:** `python3 scripts/verify-m014-s03-recommendation-explanation.py`

---

## Overview

This document specifies the **backend-owned explanation contract** for place recommendations. Every grounded place result carries structured `score_breakdown` and `explanation` fields that answer "why this place?" without frontend-fabricated reasoning.

The contract is enforced by:
- Pydantic models with `extra='forbid'` (no frontend injection)
- 70+ pytest contract tests across 16 test classes
- Chat response wiring that preserves explanation end-to-end
- Follow-up context that captures explanation keys for "why" follow-ups

---

## 1. PlaceResult Schema

Every `PlaceResult` in `ChatResponse.places` carries:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `score_breakdown` | `ScoreBreakdown` | Yes | All 8 scoring components |
| `explanation` | `PlaceExplanation` | Yes | Default if no rich metadata |
| `final_score` | `float` | Yes | Mirrors `score_breakdown.final_score` |

### ScoreBreakdown Fields (8 components)

| Field | Range | Description |
|-------|-------|-------------|
| `tree1_locality` | [0, 1] | Tree 1 locality-first score |
| `tree2_proximity` | [0, 1] | Tree 2 proximity-first score |
| `tree3_quality` | [0, 1] | Tree 3 quality-first score |
| `s_bag` | [0, 1] | Bagged average of 3 tree scores |
| `delta1_fairness` | float | Fairness correction (can be negative) |
| `delta2_access` | float | Accessibility correction |
| `final_score` | [0, 1] | Clipped final score (F2) |
| `rank` | int ≥ 1 | 1-based rank after stable sort |

---

## 2. PlaceExplanation Schema

`PlaceExplanation` uses `extra='forbid'` — arbitrary frontend fields are rejected by Pydantic.

| Field | Max Length | Default | Description |
|-------|-----------|---------|-------------|
| `rank` | — | 0 | 1-based rank (0 when not ranked) |
| `primary_reason` | 240 chars | "Recommended from grounded place data…" | Concise reason from normalized fields only |
| `matched_preferences` | 10 items | `[]` | Preference signals matched |
| `local_context` | 160 chars | "local signal unknown" | Fairness/locality context, no exact GPS |
| `score_factors` | 12 items | `{}` | Compact score fields used |
| `fairness_note` | 200 chars | "local representation metadata limited" | Fairness note from local_factor |
| `accessibility_note` | 200 chars | "accessibility metadata unknown" | From normalized accessibility fields |
| `route_summary` | 200 chars | "route metadata unavailable" | Without exact origin/user GPS |
| `provider_source` | 64 chars | `null` | Normalized provider label (google_places, goong_places, mock, cache) |
| `provider_status` | 64 chars | `null` | Normalized status (ok, empty, credentials_blocked, upstream_error, unavailable) |
| `evidence_fields_used` | 20 items | `[]` | Fields actually consumed (no fabrication) |

### Provider Source Vocabulary

| Value | Meaning |
|-------|---------|
| `google_places` | Google Places API (primary) |
| `goong_places` | Goong Places API (fallback) |
| `mock` | Test/mock provider |
| `cache` | Cached result |

### Provider Status Vocabulary

| Value | Meaning |
|-------|---------|
| `ok` | Provider returned valid results |
| `empty` | Provider returned no results |
| `credentials_blocked` | API key missing or invalid |
| `upstream_error` | Provider returned error |
| `unavailable` | Provider timeout or 5xx |

---

## 3. Provider & Credential Honesty (Inherited from S02)

The explanation contract inherits S02's provider honesty rules:

- **`provider_source`** reflects the actual tool source, never fabricated
- **`provider_status`** reflects the actual tool status (`PlaceToolStatus` value), not `business_status`
- When the reranker fails, `_grounded_results` produces fallback scores with `"fallback"` in `primary_reason`
- Google Places is the primary provider; Goong is fallback — source labels reflect which actually served

### Threading Chain

```
PlacesTool → PlaceToolResponse(source, status)
  → _reranked_results(provider_source, provider_status)
    → _build_place_explanation(provider_source, provider_status)
      → PlaceResult.explanation(provider_source, provider_status)
        → ChatResponse.places[].explanation
```

---

## 4. Redaction Boundary

**No secrets, raw payloads, or exact user GPS in explanation text.**

Redacted patterns:
- API keys (`AIza*`, `sk-*`, `gsk-*`) → `[key_redacted]`
- Secret assignments (`key=`, `token=`, `secret=`) → `[secret_redacted]`
- Phone numbers (`+84 *`, `02xx xxx xxxx`) → `[phone_redacted]`
- Text truncated to field `max_length`

**What is NOT redacted** (passthrough fields):
- `PlaceResult.display_name` — provider passthrough
- `PlaceResult.formatted_address` — provider passthrough
- `PlaceResult.types` — provider passthrough

These passthrough fields are never consumed by `_build_place_explanation`, so they cannot leak into explanation text.

---

## 5. Missing Data Behavior

When candidate data is missing, the explanation degrades gracefully:

| Missing Field | Behavior |
|--------------|----------|
| `rating` | Not in `matched_preferences`; score uses FeatureExtractor default |
| `price_level` | Not in `matched_preferences`; no budget match possible |
| `accessibility_options` | `accessibility_note` = "accessibility metadata unknown" |
| `local_factor` | Defaults to 0.5 via FeatureExtractor; `local_context` notes limited signal |
| `route_context` | `route_summary` = "route metadata unavailable" |
| All rich fields | `primary_reason` = default grounded message |

### Provider Non-OK Responses

| Status | Behavior |
|--------|----------|
| `UPSTREAM_ERROR` | `places=[]`, `reasoning_log` contains error diagnostic |
| `CREDENTIALS_BLOCKED` | `places=[]`, honest "thiếu cấu hình" message |
| `UNAVAILABLE` | `places=[]`, safe diagnostics |
| `EMPTY` | `places=[]`, follow-up context not populated |

All non-OK responses produce `fairness_audit` with `provider_non_ok` warning and a `decision_trace` with events.

---

## 6. No Frontend Fabrication

The `extra='forbid'` config on `PlaceExplanation` prevents arbitrary field injection. The contract enforces:

- `evidence_fields_used` lists only fields actually consumed by the scorer
- `matched_preferences` derives only from normalized candidate/request fields
- `primary_reason` references only actual candidate attributes
- No `frontend_fabricated_reason` or similar fields can be added

### Fabrication Prevention Tests

| Test Class | What It Verifies |
|------------|-----------------|
| `TestExplanationExtraForbid` | Pydantic rejects arbitrary extra fields |
| `TestEvidenceFieldsUsed` | evidence_fields_used only lists consumed fields |
| `TestMatchedPreferences` | matched_preferences only from normalized data |
| `TestChatResponseExplanationContract` | Chat path preserves real provider data |
| `TestRedactionBoundary` | No API keys, phones, or secrets in explanation |

---

## 7. S04 Consumer Expectations

S04 (the frontend rendering layer) can rely on:

1. **Every `PlaceResult` has `score_breakdown` and `explanation`** — never null
2. **`explanation.provider_source`** is one of: `google_places`, `goong_places`, `mock`, `cache`, or `null`
3. **`explanation.provider_status`** is one of: `ok`, `empty`, `credentials_blocked`, `upstream_error`, `unavailable`, or `null`
4. **`explanation.rank`** matches `score_breakdown.rank`
5. **Text fields are bounded** — safe to render without additional truncation
6. **No frontend fabrication needed** — all reasoning comes from backend

### Example Payload (abbreviated)

```json
{
  "places": [
    {
      "place_id": "places/ham-ninh-a",
      "display_name": "Quán Hải Sản A",
      "final_score": 0.82,
      "score_breakdown": {
        "tree1_locality": 0.85,
        "tree2_proximity": 0.70,
        "tree3_quality": 0.75,
        "s_bag": 0.767,
        "delta1_fairness": 0.0,
        "delta2_access": 0.0,
        "final_score": 0.82,
        "rank": 1
      },
      "explanation": {
        "rank": 1,
        "primary_reason": "Highly-rated seafood restaurant with strong local ownership signal",
        "matched_preferences": ["type:seafood_restaurant", "price_level:2"],
        "local_context": "Strong local signal (local_factor=0.80)",
        "score_factors": {"final_score": 0.82, "rank": 1},
        "fairness_note": "Locally-owned business detected",
        "accessibility_note": "accessibility metadata unknown",
        "route_summary": "route metadata unavailable",
        "provider_source": "google_places",
        "provider_status": "ok",
        "evidence_fields_used": ["place_id", "display_name", "score_breakdown", "rating", "price_level", "types"]
      }
    }
  ]
}
```

---

## 8. Verification

### One-Command Verifier

```bash
python3 scripts/verify-m014-s03-recommendation-explanation.py
```

Runs:
1. Test file existence check
2. Pytest contract suite (96+ tests across S03 + chat + regression)
3. PlaceResult schema inspection
4. ScoreBreakdown schema inspection
5. PlaceExplanation schema inspection (provider + evidence fields)
6. Provider honesty wiring check
7. Redaction boundary verification
8. Model import smoke test

### Individual Test Suites

```bash
# S03 explanation contract tests
python3 -m pytest backend/tests/test_m014_s03_recommendation_explanation_contract.py -v

# Chat/follow-up wiring tests
python3 -m pytest backend/tests/test_m014_s03_chat_explanation_contract.py -v

# Regression: core recommendation service
python3 -m pytest backend/tests/test_place_recommendation_service.py -v

# Regression: reranking pipeline
python3 -m pytest backend/tests/test_place_recommendation_reranking.py -v

# Regression: models
python3 -m pytest backend/tests/test_places_models.py -v

# Regression: agent place recommendations
python3 -m pytest backend/tests/test_agent_place_recommendations.py -v
```

---

## 9. Key Files

| File | Role |
|------|------|
| `backend/app/models/response.py` | `PlaceResult`, `PlaceExplanation`, `ScoreBreakdown` models |
| `agents/services/place_recommendation_service.py` | Explanation composition, redaction, provider threading |
| `backend/tests/test_m014_s03_recommendation_explanation_contract.py` | 70 contract tests (E1–E16) |
| `backend/tests/test_m014_s03_chat_explanation_contract.py` | 26 chat wiring tests (T03-1 to T03-8) |
| `scripts/verify-m014-s03-recommendation-explanation.py` | One-command verifier |

---

## 10. Credential Boundary

This verifier is **credential-free**. All S03 proof is local and contract-level:

- No live provider calls required
- No API keys needed
- No network access required
- `credentials_blocked` provider status is tested as a negative path

The verifier reports `RESULT=contract_verified` on success, or `RESULT=failed` on any local test/schema failure.
