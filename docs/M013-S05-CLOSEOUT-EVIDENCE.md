# M013/S05 Closeout Evidence — Explainability, Observability, and Closeout

**Milestone:** M013-q7pkwp (Google Places search_places hardening)
**Slice:** S05 — Explainability, Observability, and Closeout Evidence
**Date:** 2026-05-31
**Verifier:** `python3 scripts/verify-m013-s05-explainability-closeout.py`

---

## Evidence Matrix

### R036 — Typed search_places Tool Result

| Dimension | Status | Evidence |
|-----------|--------|----------|
| **Local contract** | RESULT=passed | `SearchPlacesToolResult` with `extra='forbid'`, `provider_status`, `warnings`, `reasoning_log`, `audit`; `PlaceToolStatus` and `PlaceToolSource` enums. |
| **Live proof** | _See credential status below_ | Requires valid `GOOGLE_PLACES_API_KEY`. |
| **Credential status** | `credential_blocked` when key missing; `passed` when key present and smoke check succeeds. |
| **Verifier command** | `python3 -m pytest backend/tests/test_places_models.py backend/tests/test_places_service.py -q -k SearchPlacesToolResult` |
| **Caveats** | No live Google proof without credentials; local tests use mocked provider responses. |

### R037 — No Hallucinated Place Names

| Dimension | Status | Evidence |
|-----------|--------|----------|
| **Local contract** | RESULT=passed | Deterministic composition from `PlaceResult.display_name`; tests assert no named place outside returned results. |
| **Live proof** | _See credential status below_ | Same credential gate as R036. |
| **Credential status** | `credential_blocked` / `passed` (same as R036). |
| **Verifier command** | `python3 -m pytest backend/tests/test_agent_place_recommendations.py -q -k "no_invented_place or no_document_citations or hallucinat"` |
| **Caveats** | Local tests verify deterministic composition contract only; live proof requires API key. |

### R039 — Local-Business Fairness

| Dimension | Status | Evidence |
|-----------|--------|----------|
| **Local contract** | RESULT=passed | `FairnessAudit` model with `top5_local_ratio`; ensemble reranker ensures ≥40% top-5 local when enough candidates exist; `FairnessWarningType` covers insufficient-local and missing-metadata cases. |
| **Live proof** | _See credential status below_ | Same credential gate as R036. |
| **Credential status** | `credential_blocked` / `passed` (same as R036). |
| **Verifier command** | `python3 -m pytest backend/tests/test_agent_place_recommendations.py backend/tests/test_places_models.py -q -k "fairness or Fairness or top5_local"` |
| **Caveats** | Fairness balancing is deterministic on normalized candidates; live provider may return fewer local candidates than mocked test data. |

### R040 — Fairness and Metadata Audit Trail

| Dimension | Status | Evidence |
|-----------|--------|----------|
| **Local contract** | RESULT=passed | `FairnessAudit` attached to `ChatResponse.fairness_audit`; `PlaceDecisionTrace` with 29 canonical audit events covering all decision phases. |
| **Live proof** | _See credential status below_ | Same credential gate as R036. |
| **Credential status** | `credential_blocked` / `passed` (same as R036). |
| **Verifier command** | `python3 -m pytest backend/tests/test_places_models.py -q -k FairnessAudit` |
| **Caveats** | Audit trail covers structured model contract and event emission; live metadata quality depends on provider response fields. |

### R041 — Postgres-Backed Provider Fallback Cache

| Dimension | Status | Evidence |
|-----------|--------|----------|
| **Local contract** | RESULT=passed | Cache key determinism, upsert hit/miss/stale/malformed/error; circuit breaker + cache fallback on provider timeout/500; safe degraded startup without `DATABASE_URL`. |
| **Live proof** | `live_unavailable` (no live Postgres-dependent smoke check in S05 verifier). |
| **Credential status** | N/A — cache tests are local-only. |
| **Verifier command** | `python3 -m pytest backend/tests/test_place_cache.py backend/tests/test_places_runtime_wiring.py -q` |
| **Caveats** | Postgres cache tests run with deterministic keys and mocked DB; full end-to-end Postgres integration requires `DATABASE_URL`. |

### R045 — Structured Recommendation Explanations

| Dimension | Status | Evidence |
|-----------|--------|----------|
| **Local contract** | RESULT=passed | `PlaceExplanation` model (`extra='forbid'`) with `rank`, `primary_reason`, `matched_preferences`, `local_context`, `score_factors`, `fairness_note`, `accessibility_note`, `route_summary`, `provider_source`, `provider_status`, `evidence_fields_used`; wired through both reranked and grounded recommendation paths. |
| **Live proof** | _See credential status below_ | Same credential gate as R036. |
| **Credential status** | `credential_blocked` / `passed` (same as R036). |
| **Verifier command** | `python3 -m pytest backend/tests/test_places_models.py backend/tests/test_agent_place_recommendations.py -q -k "explanation or Explanation"` |
| **Caveats** | Explanations derive only from normalized `PlaceCandidate` fields and `ScoreBreakdown`; no raw provider payloads, phone numbers, exact GPS, or API keys. Missing metadata produces explicit `unknown`/`limited` notes rather than inferred claims. |

### R046 — Trace and Verification Evidence for search_places

| Dimension | Status | Evidence |
|-----------|--------|----------|
| **Local contract** | RESULT=passed | `PlaceAuditEvent` (strict event-name validation against `frozenset`), `PlaceAuditPhase` enum, `PlaceDecisionTrace` (29 canonical events); `PlaceDecisionTracer` in service layer; `ChatResponse.decision_trace` with redacted detail and `credential_status` tracking; reasoning_log includes `audit_events` count and `credential_status` summary. |
| **Live proof** | _See credential status below_ | Same credential gate as R036. |
| **Credential status** | `credential_blocked` / `passed` (same as R036). |
| **Verifier command** | `python3 -m pytest backend/tests/test_places_models.py backend/tests/test_agent_place_recommendations.py backend/tests/test_places_runtime_wiring.py -q -k "decision_trace or audit_event or AuditEvent or DecisionTrace or tracer"` |
| **Caveats** | Decision trace covers all search_places phases (request → provider → cache → route → filter → rerank → fairness → compose → credential); `elapsed_ms` timing on all events; no secrets in serialized trace. |

---

## Credential Status Semantics

| Status | Meaning | Exit Code |
|--------|---------|-----------|
| `RESULT=passed` | All local tests pass AND live Google Places smoke check succeeds with valid `GOOGLE_PLACES_API_KEY`. | 0 |
| `RESULT=credential_blocked` | All local tests pass but `GOOGLE_PLACES_API_KEY` is missing, fake, or placeholder. Live proof cannot be claimed. | 0 |
| `RESULT=failed` | Local test failure or malformed response — not a credential issue. | 1 |
| `RESULT=live_unavailable` | Credentials present but provider timeout/5xx — no live proof, local contract still holds. | 0 |

---

## Local Verifier Commands (Aggregate)

```bash
# Full S05 closeout verification (single command):
python3 scripts/verify-m013-s05-explainability-closeout.py

# Individual slice regression (S01-S04):
python3 scripts/verify-m013-s01-search-places.py
python3 scripts/verify-m013-s02-fairness-metadata.py
python3 scripts/verify-m013-s03-provider-fallback.py
python3 scripts/verify-m013-s04-preferences-cultural-context.py
```

---

## Live Google Places Smoke Check

When `GOOGLE_PLACES_API_KEY` is present and non-placeholder, the verifier attempts a single bounded Text Search request to `https://places.googleapis.com/v1/places:searchText` with `X-Goog-FieldMask`. A successful 200 response with at least one place candidate is recorded as live proof.

- **Timeout:** 15 seconds (respects circuit-breaker conventions).
- **Failure modes:** 401/403 → `credential_blocked`; timeout/5xx → `live_unavailable`; malformed response → `failed`.
- **No secrets logged:** Only request ID, HTTP status, and candidate count are printed.

---

## Slice-Level Promises

| Promise | Status |
|---------|--------|
| Every returned place has structured `why-this-recommendation` data (`PlaceExplanation`) | ✅ Local pass |
| `PlaceDecisionTrace` with 29 canonical audit events attached to `ChatResponse.decision_trace` | ✅ Local pass |
| Structured logger events with trace correlation and credential status tracking | ✅ Local pass |
| Closeout evidence records local, credential-blocked, and live-proof status distinctly | ✅ Local pass (this document) |
| Credential-aware verifier exits 0 with correct status vocabulary | ✅ Local pass (verifier script) |
