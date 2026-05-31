# M014-S02 Google Places Primary Rich Contract — Diagnostics Handoff

**Date:** 2026-05-31  
**Milestone:** M014 (UX Enhancement Phase 2)  
**Slice:** S02 — Google Places Primary Rich Contract  
**For consumers:** S03 (Explanation), S06 (Fairness), and any slice reading `search_places` results.

---

## 1. Provider Topology

| Provider | Role | Config key | Base URL |
|----------|------|-----------|----------|
| **Google Places API (New)** | Primary | `GOOGLE_PLACES_API_KEY` | `https://places.googleapis.com/v1/` |
| **Goong Places** | Fallback | `GOONG_API_KEY` | `https://api.goong.io/` |

**Composition:** `DualPlacesService` — Google-first with Goong fallback.
- Google key present → Google attempted first; on failure (credential blocked, upstream error, unavailable) → Goong fallback if Goong key configured.
- Google key absent → Goong-only path with `primary_source=google_places` metadata.
- Neither key → `CREDENTIALS_BLOCKED` with `no_provider_configured` reason.

---

## 2. Envelope Contract

Every `search_places` call returns a `SearchPlacesToolResult` with these top-level fields:

| Field | Type | Description |
|-------|------|-------------|
| `status` | `PlaceToolStatus` enum | `ok`, `empty`, `credentials_blocked`, `upstream_error`, `invalid_request`, `unavailable` |
| `source` | `PlaceToolSource` enum | `google_places`, `goong_places`, `cache`, `mock` |
| `provider_status` | `ProviderStatus` | Safe HTTP status, provider code, sanitized message, request ID |
| `candidates` | `list[PlaceCandidate]` | Normalized place candidates (see §4) |
| `request_metadata` | `dict` | Credential/provider/fallback diagnostics (see §3) |
| `warnings` | `list[str]` | User-safe warning messages |
| `reasoning_log` | `list[str]` | Step-by-step reasoning (no secrets) |
| `place_recommendation_status` | `PlaceRecommendationStatus` | Filter/recommendation diagnostics (see §5) |
| `audit` | `dict` | Redacted audit trail (no secrets, no raw payloads) |

---

## 3. Credential & Provider Diagnostics (`request_metadata`)

Every response carries these diagnostic keys in `request_metadata`:

| Key | Values | Meaning |
|-----|--------|---------|
| `credential_status` | `live`, `blocked`, `unavailable` | Whether the attempted provider's API key is configured and functional |
| `provider_attempted` | `google_places`, `goong_places`, `google_places->goong_places` | Which provider(s) were called |
| `primary_source` | `google_places` (always) | The designated primary provider |
| `fallback_source` | `goong_places`, `cache`, `cache_stale`, `none` | What was used when primary failed |
| `fallback_reason` | `google_credentials_blocked`, `google_upstream_error:*`, `google_unavailable:*`, `google_credential_missing`, `no_provider_configured` | Why fallback was triggered |
| `endpoint` | `google_text_search`, `google_nearby_search`, `google_detail`, `goong_text_search`, `goong_nearby_search`, `goong_detail` | Which provider endpoint was hit |
| `field_mask` | Google field mask string | Fields requested from Google Places API New |
| `result_count` | int | Number of candidates in the response |
| `provider_contract_version` | `v1` (currently) | Schema version — bump when field mask or normalization changes |
| `language_code` | `vi`, `en` | Locale used for the request |
| `max_result_count` | int | Requested result limit |

---

## 4. Rich Field Mask & Candidate Fields

### Google Places API New Field Mask (18 fields)

```
places.id
places.displayName
places.formattedAddress
places.shortFormattedAddress
places.location
places.types
places.primaryType
places.rating
places.userRatingCount
places.priceLevel
places.regularOpeningHours
places.currentOpeningHours
places.businessStatus
places.accessibilityOptions
places.nationalPhoneNumber
places.internationalPhoneNumber
places.googleMapsUri
places.websiteUri
```

### PlaceCandidate Fields (normalized, provider-agnostic)

| Field | Source (Google) | Source (Goong) | Notes |
|-------|----------------|----------------|-------|
| `place_id` | `id` | `place_id` | |
| `display_name` | `displayName.text` | `name` | |
| `formatted_address` | `formattedAddress` | `formatted_address` / `vicinity` | |
| `short_formatted_address` | `shortFormattedAddress` | `None` | Goong does not provide this |
| `location` | `location.{lat,lng}` | `geometry.location.{lat,lng}` | |
| `types` | `types[]` | `types[]` | |
| `primary_type` | `primaryType` | `types[0]` | |
| `rating` | `rating` | `rating` | |
| `user_rating_count` | `userRatingCount` | `user_ratings_total` | |
| `price_level` | `priceLevel` (enum→int 0-4) | `None` | Goong does not provide price level |
| `open_now` | `currentOpeningHours.openNow` | `opening_hours.open_now` | |
| `business_status` | `businessStatus` | `None` | Goong does not provide this |
| `accessibility_options` | `accessibilityOptions{}` | `{}` | Goong does not provide accessibility |
| `national_phone_number` | `nationalPhoneNumber` | `international_phone_number` / `formatted_phone_number` | |
| `international_phone_number` | `internationalPhoneNumber` | `international_phone_number` | |
| `map_uri` | `googleMapsUri` | Goong map URL | |
| `website_uri` | `websiteUri` | `website` | |
| `fairness_tags` | Derived from accessibility_options | `["accessibility_unknown"]` | |
| `route_context` | Computed via haversine | Computed via haversine | Distance from origin |

---

## 5. Recommendation Status Diagnostics

`place_recommendation_status` provides filter-level visibility:

| Key | Type | Description |
|-----|------|-------------|
| `provider_places_returned` | int | Raw places from provider |
| `candidates_after_normalization` | int | Surviving normalization |
| `filters_applied` | `list[str]` | Applied filters (e.g. `max_result_count=10`) |
| `reason` | str | Human-readable outcome explanation |

---

## 6. Status & Fallback Decision Matrix

| Google status | Goong key? | Final `status` | Final `source` | Notes |
|--------------|-----------|---------------|---------------|-------|
| `ok` / `empty` | — | Google status | `google_places` | No fallback needed |
| `credentials_blocked` | Yes | Goong result | `goong_places` | Google skipped, Goong tried |
| `credentials_blocked` | No | `unavailable` | `google_places` | Both unavailable |
| `upstream_error` | Yes | Goong result | `goong_places` | Google failed, Goong tried |
| `upstream_error` | No | `unavailable` | `google_places` | No fallback available |
| `unavailable` (circuit/cache) | Yes | Goong or cache result | varies | Circuit breaker may open |
| Neither key configured | — | `credentials_blocked` | `google_places` | `no_provider_configured` |

---

## 7. Startup Diagnostics

On backend startup, the following structured log event is emitted:

```json
{
  "event": "places.recommendation_configured",
  "primary_provider": "google_places",
  "fallback_provider": "goong_places",
  "google_key_configured": true,
  "goong_key_configured": true
}
```

If initialization fails:
```json
{
  "event": "places.recommendation_init_failed",
  "error_type": "ExceptionClassName"
}
```

---

## 8. Redaction Guarantee

The following are **never** included in any response field, audit log, reasoning log, or structured metadata:
- API keys (Google or Goong)
- Exact GPS coordinates beyond what the request object already carries
- Phone numbers in audit logs
- Raw upstream JSON payloads
- Internal file paths (`.gsd/`, `.planning/`)

---

## 9. Live-Proof Caveat

> **Credential-blocked ≠ live validation failure.** When `GOOGLE_PLACES_API_KEY` is absent, fake, or redacted in the environment, the contract tests pass against mock fixtures and the verifier reports `RESULT=credential_blocked`. This is the expected behavior for environments without live Google credentials. A live provider success test requires a valid `GOOGLE_PLACES_API_KEY` with Places API (New) enabled.

---

## 10. Files & Test Surface

| File | Purpose |
|------|---------|
| `backend/app/models/places.py` | Contracts: `PlaceCandidate`, `SearchPlacesToolResult`, `ProviderStatus`, field mask, audit events |
| `agents/tools/places_service.py` | Implementation: `GooglePlacesService`, `GoongPlacesService`, `DualPlacesService`, circuit breaker |
| `backend/tests/test_m014_s02_google_places_primary_contract.py` | 87 contract tests (endpoint, field mask, normalization, credential diagnostics, error handling, redaction, fallback) |
| `backend/tests/test_places_runtime_wiring.py` | 12 runtime wiring tests (provider composition, startup diagnostics) |
| `backend/tests/test_places_models.py` | Model validation tests |
| `backend/tests/test_place_recommendation_service.py` | Recommendation service integration tests |
| `backend/tests/test_agent_place_recommendations.py` | Agent recommendation pipeline tests |
| `scripts/verify-m014-s02-google-places-primary.py` | S02 verifier (9 checks: 8 local + 1 live) |

**Total test count:** 551 tests (87 contract + 12 wiring + models + recommendation service + agent recommendations)

---

## 11. Downstream Consumption Guide

### For S03 (Explanation)
- Read `request_metadata.provider_attempted` and `request_metadata.fallback_source` to explain which provider answered.
- Read `request_metadata.field_mask` to explain what data fields were requested.
- Read `reasoning_log` entries for human-readable explanation of the result path.
- Check `warnings` for degraded-mode indicators (stale cache, provider unavailable).

### For S06 (Fairness)
- Use `FairnessAudit` model attached to recommendation results — includes `candidate_count`, `result_count`, `top5_local_ratio`, `missing_local_factor_count`, `provider_status`, and `warnings`.
- `PlaceAuditEvent` / `PlaceDecisionTrace` on `ChatResponse` provides the full decision path with phase labels (`request`, `provider`, `cache`, `filter`, `rerank`, `fairness`, `compose`, `credential`).
- `PLACE_AUDIT_EVENTS` frozenset defines the canonical event vocabulary for machine-readable audit analysis.

### For any consumer
- Check `status` first: only `ok` means full results; `empty` means valid but no matches; everything else means degraded or blocked.
- Check `source` to know which provider produced the candidates.
- Check `request_metadata.credential_status` to diagnose whether credentials are the root cause.
- Never parse `candidates` field-by-field differently by source — `PlaceCandidate` is normalized and provider-agnostic.
