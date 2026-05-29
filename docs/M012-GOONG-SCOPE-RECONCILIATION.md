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
