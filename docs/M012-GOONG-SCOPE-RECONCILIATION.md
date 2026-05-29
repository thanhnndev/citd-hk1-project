# M012 Goong Scope Reconciliation

## Purpose

This document defines the M012 validation boundary for the Goong migration. It maps the active Goong producers, normalized contracts, consumers, credential seams, and rerunnable verifier surfaces so future evidence can distinguish completed migration proof from credential-blocked or out-of-scope product requirements.

M012 validates Goong-owned Places, Routes, browser map rendering, and closeout evidence surfaces only. It does not claim unrelated product requirements, live credentialed success without real credentials, or browser tile success unless the browser verifier reports terminal `RESULT=passed`.

## Credential Boundary

| Credential | Visibility | Used By | Proves | Blocked-Live Status |
|---|---|---|---|---|
| `GOONG_API_KEY` | Server-only | `agents/tools/places_service.py`, `agents/tools/routes_service.py`, `scripts/verify-goong-live.py` | Live Places candidate normalization and live Routes metrics when real credentials are present | Missing, fake, or placeholder values produce `RESULT=credential_blocked`; this is executable blocked-live evidence, not credentialed `RESULT=passed` proof. |
| `NEXT_PUBLIC_GOONG_MAPTILES_KEY` | Browser-public | `frontend/src/components/map/goong-place-map.tsx`, `frontend/tests/s06-goong-map-live.test.mjs` | Browser Goong style/tile loading, map pins, and marker selection when a usable public tile key is present | Missing, fake, or placeholder values produce `RESULT=credential_blocked`; this does not prove live browser tile rendering. |

Rules:

- Browser code must not read or expose `GOONG_API_KEY`.
- Backend Places and Routes code must not depend on `NEXT_PUBLIC_GOONG_MAPTILES_KEY`.
- Evidence must record sanitized terminal statuses and credential presence classifications only; no raw keys, raw Places payloads, raw Routes payloads, or raw tile responses.
- `RESULT=credential_blocked` is a valid executable outcome for blocked-live proof, but only `RESULT=passed` with real credentials is credentialed live success.

## Producer, Contract, Consumer Map

| Boundary Surface | Role | Producer | Normalized Contract Or Output | Consumer | Credential Seam | Rerunnable Evidence Surface |
|---|---|---|---|---|---|---|
| Backend Places | Goong Places producer | `agents/tools/places_service.py` (`GoongPlacesService`) | `PlaceToolResponse` with sanitized `PlaceCandidate` objects, coordinate-bearing locations when upstream data supports them, safe status/error envelopes | `PlaceRecommendationService`, agent chat flow, `scripts/verify-goong-live.py` | Reads server-only `GOONG_API_KEY` through `Settings`; returns credential errors when absent | `cd backend && pytest -q tests/test_places_models.py tests/test_places_service.py tests/test_place_recommendation_service.py tests/test_agent_place_recommendations.py --tb=short`; live path: `python3 scripts/verify-goong-live.py` |
| Backend Routes | Goong Routes producer | `agents/tools/routes_service.py` (`GoongRoutesService`) | Distance Matrix route metrics and `RouteContext` enrichment without exposing upstream payloads | `PlaceRecommendationService`, `scripts/verify-goong-live.py` | Reads server-only `GOONG_API_KEY`; circuit breaker degrades route enrichment safely | `cd backend && pytest -q tests/test_routes_service.py tests/test_place_recommendation_reranking.py --tb=short`; live path: `python3 scripts/verify-goong-live.py` |
| App Configuration | Server credential contract | `backend/app/core/config.py` | `Settings.GOONG_API_KEY` defaults to blank so app import/test paths can run while Goong calls fail honestly at runtime | Places and Routes services, live verifier | Server-only key; no browser-public export | `cd backend && pytest -q tests/test_config.py --tb=short` |
| Backend App Wiring | Runtime producer wiring | `backend/app/main.py` | `app.state.places_service` and `app.state.place_recommendation_service` configured with Goong Places and Routes services | `/chat` agent path and recommendation flow | Server-only `GOONG_API_KEY` remains inside backend process | Backend mocked regression command recorded in `docs/M012-GOONG-VERIFICATION-EVIDENCE.md` |
| Backend Live Verifier | Credential-aware live verifier | `scripts/verify-goong-live.py` | Sanitized phase labels: `CONFIG`, `PLACES_RESPONSE`, `CANDIDATES`, `ROUTES_RESPONSE`, `RESULT`, plus sanitized `ERROR` or `VALIDATION_ERRORS` | Human audit trail, M012 evidence document, future release checks | Uses `GOONG_API_KEY` only; classifies missing/fake/placeholder credentials before live calls | `python3 scripts/verify-goong-live.py`; terminal `RESULT=credential_blocked`, `RESULT=passed`, or `RESULT=failed` |
| Frontend Goong Map Renderer | Browser map producer/renderer | `frontend/src/components/map/goong-place-map.tsx` | Mapbox GL instance using Goong style URL, coordinate pins, marker selection callbacks, token-missing and map-unavailable UI states | `PlaceProofMap` and `/[locale]/map` page | Uses browser-public `NEXT_PUBLIC_GOONG_MAPTILES_KEY`; does not read `GOONG_API_KEY` | `cd frontend && node --test tests/s03-map-proof-contract.test.mjs`; browser live path: `cd frontend && node --test tests/s06-goong-map-live.test.mjs` |
| Product Map Consumer | Product inspection surface | `frontend/src/components/map/place-proof-map.tsx` and `frontend/src/app/[locale]/map/page.tsx` | `/vi/map` and localized map page fetch `/api/chat`, render returned place cards, coordinates, Goong map pins, and selection details | Users and browser verifier | Consumes public tile key only for rendering; product data comes from chat API response | `cd frontend && node --test tests/s06-goong-map-live.test.mjs`; production build evidence: `cd frontend && bun run build` |
| S05 Zero-Reference Verifier | Migration closeout guardrail | `scripts/verify-s05-zero-<legacy-provider>-references.py` | `RESULT=passed` when active code/docs/config/tests/manifests retain the Goong-only boundary and stale provider references stay absent | Executors validating migration cleanup | No credentials | `python3 scripts/verify-s05-zero-<legacy-provider>-references.py` |
| Evidence Document | Human-readable audit surface | `docs/M012-GOONG-VERIFICATION-EVIDENCE.md` | Completed mocked gates, build gates, live verifier outcomes, credential-blocked interpretation, and sanitization notes | Milestone reviewers and future task executors | Records statuses without secrets | Read alongside this document; rerun the commands named in each section before updating live claims |

## In-Scope Requirement Reconciliation

M012 in scope:

- Goong Places service produces normalized backend candidate contracts.
- Goong Routes service enriches candidates with route metrics through backend-owned calls.
- Backend app wiring uses Goong Places and Routes services for recommendation flow.
- Browser map rendering uses Goong tile/style configuration with a public browser key only.
- Credential-dependent checks clearly distinguish blocked-live status from live success.
- Active migration cleanup remains guarded by the S05 zero-reference verifier.
- Evidence documents are sanitized and rerunnable.

M012 out of scope:

- Claiming live Goong Places or Routes success when `scripts/verify-goong-live.py` reports `RESULT=credential_blocked`.
- Claiming live browser tile rendering when `frontend/tests/s06-goong-map-live.test.mjs` reports `RESULT=credential_blocked`.
- Proving unrelated product requirements such as complete business onboarding, trained ranking models, production auth policy, observability vendor delivery, or non-Goong data ingestion outcomes.
- Publishing secrets or raw upstream provider payloads as audit evidence.

## Requirement Scope Matrix

This matrix is the M012 reconciliation surface for requirement integrity rules R032 and R034. It does not replace `.gsd/REQUIREMENTS.md`; no official requirement updater was available in this execution environment, so the evidence-backed boundary remains documented here.

| Requirement | Current Requirement Status | M012 Scope Status | M012 Evidence And Limits | Boundary Interpretation |
|---|---|---|---|---|
| R008 | validated | M012 validated at mocked/static/build level; credentialed proof pending | S05 zero-reference gate reported `RESULT=passed`; backend Goong Places/Routes regression suite passed; frontend Goong map contract, chat E2E, and production build passed; backend live verifier currently reports `RESULT=credential_blocked` without a real `GOONG_API_KEY`. | M012 supports the Goong-only Places/Routes/map migration and proves blocked-live behavior. It must not be cited as credentialed live provider success until `scripts/verify-goong-live.py` reports terminal `RESULT=passed` with real credentials. |
| R017 | validated | Supported by M012, not broadened | Backend Goong Places producer returns normalized `PlaceToolResponse`/`PlaceCandidate` contracts under mocked regression tests and remains the agent-owned producer for place candidates. | M012 preserves the backend Places ownership boundary and migration evidence. It does not add a new claim about live Hàm Ninh candidate quality without credentialed Goong proof. |
| R019 | validated | Supported by M012, not broadened | Frontend `/map` and `PlaceProofMap` consume chat/API place results, render list/detail/pin-ready data, and use `GoongPlaceMap` with `NEXT_PUBLIC_GOONG_MAPTILES_KEY`; static contract/build gates pass. | M012 validates the Goong renderer and browser credential seam at static/build level. Live tile rendering remains pending until the browser verifier reports terminal `RESULT=passed` with a usable public map tiles key. |
| R020 | validated | M012 directly reinforces fail-honest behavior | Backend live verifier classifies missing/fake/placeholder server credentials as `RESULT=credential_blocked`; browser verifier classifies missing/placeholder public map tile credentials as `RESULT=credential_blocked`; evidence records sanitized status only. | `credential_blocked` is successful blocked-live evidence and failure visibility, not live provider success. This distinction is part of the M012 validation boundary. |
| R021 | validated | Supported by M012, not broadened | Goong Places candidate contracts preserve fairness-ready and pin-ready fields through backend response models and frontend map/list consumers; regression gates cover mocked contract shape. | M012 keeps the feature seam available for ranking and inspection. It does not claim new fairness ranking, trained ranking models, or live field completeness beyond mocked/static evidence. |
| R032 | active | M012 complies through this reconciliation artifact | Claims in this document are tied to concrete scripts, tests, builds, and evidence docs; credentialed live success is explicitly marked pending when only `credential_blocked` evidence exists. | Requirement status changes should only occur through an official updater or future validated evidence. This task intentionally leaves `.gsd/REQUIREMENTS.md` untouched. |
| R034 | active | M012 complies by keeping major gaps explicit | Credentialed backend Goong proof, credentialed browser tile proof, and unrelated product capabilities remain open or out-of-scope instead of being silently counted as completed by migration tests. | M012 narrows its closeout to evidence-backed Goong migration coverage and defers broader/unrelated work to its owning requirements. |

## Out-of-Scope Active Requirement Gaps

These active requirements remain visible because they are not completed by the M012 Goong migration. Their active status is not evidence of M012 failure; it prevents migration evidence from overclaiming unrelated product readiness.

| Requirement | Active Gap | M012 Relationship | Guardrail |
|---|---|---|---|
| R007 | RAG cultural Q&A with Qdrant/hybrid retrieval still needs credentialed embedding/Qdrant proof and RAGAS/live LLM evidence where noted in `.gsd/REQUIREMENTS.md`. | Out of scope/unrelated to Goong Places, Routes, and map tile migration. | Do not cite Goong verifier, map build, or zero-reference results as RAG/Qdrant/OpenAI/RAGAS validation. |
| R010 | Compliance gaps remain for semantic cache, RAGAS CI/CD, monthly fairness audit script, and unified audit script. | Out of scope/unrelated to Goong provider migration except for general evidence honesty. | Do not treat sanitized Goong evidence as compliance subsystem delivery. |
| R011 | Admin endpoints such as `/admin/eval/trigger`, `/admin/traces`, and `/admin/ingest` remain unimplemented or not fully wired as described. | Out of scope/unrelated to M012 Goong runtime proof. | Do not infer admin API readiness from backend Goong tests or frontend map build success. |
| R026 | Frontend `/admin` dashboard, corpus stats, evaluation results, trace viewer UI, and authenticated dashboard flow remain active gaps. | Out of scope/unrelated to Goong map/Places evidence. | Do not cite `/vi/map` or chat place proof surfaces as admin dashboard validation. |
| R028 | Chat UX polish gaps remain for welcome screen, suggested prompts, copy/retry actions, and typing animations. | Out of scope/unrelated to provider migration, although chat place cards and map proof surfaces may continue to work. | Do not broaden M012 frontend build success into complete chat UX polish. |

## Verification Surfaces Executors Can Rerun

Use these commands from the repository root unless a command changes into a subdirectory:

```bash
test -s docs/M012-GOONG-SCOPE-RECONCILIATION.md
python3 scripts/verify-s05-zero-<legacy-provider>-references.py
python3 scripts/verify-goong-live.py
cd backend && pytest -q tests/test_config.py tests/test_places_models.py tests/test_places_service.py tests/test_routes_service.py tests/test_place_recommendation_service.py tests/test_place_recommendation_reranking.py tests/test_agent_place_recommendations.py tests/test_verify_goong_live.py --tb=short
cd frontend && node --test tests/s03-map-proof-contract.test.mjs tests/s06-goong-map-live.test.mjs
cd frontend && bun run build
```

Interpretation:

- `test -s` proves this reconciliation artifact exists and is non-empty.
- Zero-reference `RESULT=passed` proves the active migration guardrail still holds.
- Backend/frontend regression commands prove mocked contracts, static map boundaries, and build health.
- Live verifier `RESULT=credential_blocked` proves the verifier executed but credentials were missing, fake, or placeholder.
- Live verifier `RESULT=passed` is the only acceptable claim for credentialed live success on its respective backend or browser path.
