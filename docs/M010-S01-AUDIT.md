# M010/S01 Requirements Audit Report

**Milestone:** M010 — Quality & Completeness Audit  
**Slice:** S01 — Requirements Audit and Evidence Sweep  
**Date:** 2026-05-23  
**Auditor:** Auto-mode (GSD)  
**Total Requirements Audited:** 25 (R001–R028, excluding gaps; R012 out-of-scope)

---

## Executive Summary

| Verdict | Count | Requirement IDs |
|---|---|---|
| **PASS (validated)** | 20 | R001, R002, R003, R004, R005, R006, R009, R013, R014, R015, R016, R017, R018, R019, R020, R021, R022, R023, R024, R025 |
| **CREDENTIAL_BLOCKED** | 2 | R007, R008 |
| **FAIL** | 5 | R010, R011, R026, R027, R028 |
| **OUT_OF_SCOPE** | 1 | R012 (anti-feature) |
| **Total** | **25** | |

**Overall health:** 80% validated (20/25), 8% credential-blocked (2/25), 20% fail (5/25).  
The 2 credential-blocked items are not failures — they require external API credentials for live proof.

---

## Credential-Blocked Convention

When a verification script requires external API keys (OPENAI_API_KEY, Google Places API key, Qdrant instance) that are not available in the execution environment, the script exits with code **0** and prints `RESULT=credential_blocked`. This is **not a failure** — it is a documented gap that should be re-verified when credentials become available. All credential-blocked tests are skipped in `pytest` with `@pytest.mark.skipif` guards.

---

## Per-Requirement Audit

### R001 — Landing page renders at locale-aware root route
- **Status:** ✅ PASS
- **Validated by:** M002-6yge5y/S01 (landing contract) + M002-6yge5y/S04 (browser verification)
- **Evidence files:** `frontend/src/components/landing/` (7 components), `frontend/src/app/[locale]/page.tsx`
- **Key files:** `frontend/src/components/landing/` directory, `frontend/src/app/[locale]/page.tsx`
- **Notes:** All 7 sections present (Hero, Problem, Solution, Responsible AI, Algorithm Showcase, Tech Stack, Demo CTA). Verified at /vi and /en.

### R002 — Locale-aware navigation header/footer
- **Status:** ✅ PASS
- **Validated by:** M002-6yge5y/S02 (19-test navigation suite) + M002-6yge5y/S04 (browser verification)
- **Evidence files:** M002/S02 test suite, M002/S04 browser E2E
- **Key files:** `frontend/src/components/layout/site-header.tsx`, `site-footer.tsx`, `locale-switcher.tsx`
- **Notes:** Header/footer work across all routes with locale preservation.

### R003 — Frontend builds cleanly (lint, type-check, build)
- **Status:** ✅ PASS
- **Validated by:** M002-6yge5y/S04
- **Evidence files:** `bun run lint` (exit 0), `bun run type-check` (exit 0), `bun run build` (exit 0), 29/29 browser tests, zero console errors
- **Notes:** Clean build in both vi and en locales.

### R004 — Chat/Map/Architecture placeholder shells
- **Status:** ✅ PASS
- **Validated by:** M002-6yge5y/S03 + M002-6yge5y/S04
- **Evidence files:** M002/S03 placeholder implementation, M002/S04 browser verification
- **Key files:** `frontend/src/components/placeholder/placeholder-page.tsx`
- **Notes:** Honest placeholders, no fake behavior, localized, navigation back to landing.

### R005 — Landing page responsive + WCAG 2.2 AA
- **Status:** ✅ PASS
- **Validated by:** M002-6yge5y/S04
- **Evidence files:** M002/S04 browser tests at 375px, 768px, 1280px
- **Notes:** No horizontal overflow. Accessibility spot-checks pass.

### R006 — Chat endpoint POST /chat + GET /chat/stream SSE
- **Status:** ✅ PASS
- **Validated by:** M004/S05
- **Evidence files:** `cd backend && python -m pytest tests/ -q --tb=short` — 230 passed, 14 skipped; S05 browser E2E
- **Key files:** `backend/app/routers/chat.py`, `agents/graph/agent_service.py`
- **Notes:** AgentService with session-keyed memory. SSE streaming proven in browser E2E.

### R007 — RAG cultural Q&A pipeline with Qdrant + RAGAS
- **Status:** 🔒 CREDENTIAL_BLOCKED
- **Evidence files:** M009-arwc9e/S02 — 24 tests pass (8 embed endpoint + 16 hybrid search), 5 integration tests skip with credential_blocked
- **Key files:** `backend/app/routers/admin.py` (POST /admin/embed), `agents/tools/embedding_service.py`, `agents/tools/qdrant_service.py`
- **Gap:** Requires valid OPENAI_API_KEY and running Qdrant instance for end-to-end live proof. RAGAS evaluation deferred (requires live LLM).
- **Partial code:** POST /admin/embed endpoint exists. Dense+sparse hybrid retrieval via HybridRetriever. BM25 vectorizer in app.state.

### R008 — Google Places and Routes integration
- **Status:** 🔒 CREDENTIAL_BLOCKED
- **Evidence files:** M005/S04 verifier reports RESULT=credential_blocked. Backend 53 tests pass confirming failure envelopes.
- **Key files:** `agents/tools/places_service.py`, `agents/tools/routes_service.py`, `agents/services/place_recommendation_service.py`
- **Gap:** Requires valid Google Places API key for live proof. Circuit breaker fallback to SQLite not yet implemented. Routes API integration untested live.
- **Partial code:** Places service code exists. Backend tests confirm failure envelope handling.

### R009 — Ensemble Re-ranking (3 trees + 2 corrections)
- **Status:** ✅ PASS
- **Validated by:** M006-doudmh/S02 (55 unit tests) + S03 (366 integration tests) + S05 (E2E)
- **Evidence files:** 366+ integration tests, ≥40% local constraint verified
- **Key files:** `agents/ml/ensemble_reranker.py`, `agents/ml/feature_extractor.py`
- **Notes:** ScoreBreakdown exposes all 8 fields (tree1_locality, tree2_proximity, tree3_quality, s_bag, delta1_fairness, delta2_access, final_score, rank).

### R010 — Responsible AI 5-axis compliance
- **Status:** ❌ FAIL
- **Evidence files:** Individual axes have partial coverage only — no unified audit exists
- **Key files:** `backend/app/services/langfuse_service.py`, `agents/guardrails/grounded_answer.py`
- **Gap:** Missing: semantic cache (Redis 8.0), RAGAS CI/CD pipeline, monthly fairness audit script, comprehensive 5-axis audit script. Individual axes partially covered: REL-01/REL-04 via R006/R015 (citations), ROB-01 via guardrails, EXP-04 via Langfuse tracing.
- **What's needed:** Unified 5-axis audit script (M010/S02), session durability verification (M010/S03), per-node timeout + circuit breaker (M010/S04), semantic cache implementation (future).

### R011 — Admin endpoints with JWT auth
- **Status:** ❌ FAIL
- **Evidence files:** Only POST /admin/embed exists with zero auth. No JWT middleware on admin routes.
- **Key files:** `backend/app/routers/admin.py` (only /embed endpoint), `backend/app/middleware/auth.py` (JWT pattern exists)
- **Gap:** Admin routes need JWT protection. Three additional endpoints need implementation: /admin/eval/trigger, /admin/traces, /admin/ingest.
- **What's needed:** JWT middleware wiring + 3 new endpoints + frontend dashboard (M010/S06).

### R012 — Anti-features (no booking/payment/CRM/fine-tuning/mobile)
- **Status:** ⏭️ OUT_OF_SCOPE
- **Evidence:** Confirmed absent from codebase. No booking, payment, CRM, fine-tuning, or mobile code found.
- **Notes:** Explicitly excluded from pass/fail count per requirements classification.

### R013 — Normalize tourism_documents.jsonl into RAG corpus
- **Status:** ✅ PASS
- **Validated by:** M009-arwc9e/S01
- **Evidence files:** 607 proposition chunks, all 9 required fields present. 165 backend tests pass. Ingestion script exits 0 with structured stats.
- **Key files:** `data/tourism_documents.jsonl`, `agents/tools/proposition_chunker.py`, `agents/tools/corpus_loader.py`
- **Notes:** `scripts/ingest_propositions.py` exits 0. Stats: vi=607, high=19/medium=588, avg 124.5 chars/proposition.

### R014 — Real chat UI with submit/loading/error/citations
- **Status:** ✅ PASS
- **Validated by:** M004/S05
- **Evidence files:** type-check, lint, build pass. Browser E2E verifies streaming, citations, follow-up, no-evidence.
- **Key files:** `frontend/src/components/chat/chat-interface.tsx`, `message-bubble.tsx`, `citation-card.tsx`

### R015 — Grounded answers with citations + honest no-evidence
- **Status:** ✅ PASS
- **Validated by:** M009-arwc9e/S03
- **Evidence files:** 21 pytest tests pass (10 dense-only retrieval + 11 AgentService integration)
- **Key files:** `agents/guardrails/grounded_answer.py`, `agents/graph/agent_service.py`
- **Notes:** Citations verified against 71 unique corpus titles. No-evidence compose verified.

### R016 — E2E browser chat flow with cultural question + citation
- **Status:** ✅ PASS
- **Validated by:** M004/S05
- **Evidence files:** `node tests/s05-chat-e2e.test.mjs` passes against real Next.js chat UI + API proxy
- **Notes:** Hàm Ninh cultural question, streamed grounded cited answer, same-session follow-up, no-evidence, fallback all verified.

### R017 — Maps Agent returns grounded place candidates from Places API
- **Status:** ✅ PASS
- **Validated by:** M005-muzhoo/S02
- **Evidence files:** 49 tests pass across Places models/service, chat endpoint, SSE, agent recommendations
- **Key files:** `agents/services/place_recommendation_service.py`, `agents/tools/places_service.py`
- **Notes:** Chat place intents return ChatResponse.places from Places tool candidates only.

### R018 — No hallucinated places
- **Status:** ✅ PASS
- **Validated by:** M005-muzhoo/S02
- **Evidence files:** Invariant tests filter all place_ids against PlaceToolResponse.candidates
- **Notes:** All error paths return places=[] with safe copy. No LLM-invented locations.

### R019 — /map surface displays place results
- **Status:** ✅ PASS
- **Validated by:** M005-muzhoo/S03
- **Evidence files:** Backend ChatResponse contract tests, frontend type-check, node:test map proof contracts
- **Key files:** `frontend/src/components/map/place-proof-map.tsx`, `frontend/src/app/[locale]/map/page.tsx`
- **Notes:** Covers list/detail/pin-ready states, Google Maps links, no-results, fallback/unavailable, missing-coordinate, request-error states.

### R020 — Google Places failures handled fail-honestly
- **Status:** ✅ PASS
- **Validated by:** M005-muzhoo/S04
- **Evidence files:** Live verifier credential_blocked, fake-key redaction (0 matches), 53 backend tests, 14 frontend build contract tests
- **Key files:** `docs/M005-PLACES-VERIFICATION-EVIDENCE.md`
- **Notes:** Evidence doc covers missing key, quota/auth errors, timeout, repeated failures/circuit breaker, zero results, and map-render failure fallback.

### R021 — Places contracts preserve fairness ranking fields
- **Status:** ✅ PASS
- **Validated by:** M005-muzhoo/S03
- **Evidence files:** Backend tests confirm ChatResponse.places preserves rating, review_count, price_level, accessibility, location, types, google_maps_uri, open_now, business_status
- **Notes:** All fairness-ready and pin-ready fields preserved.

### R022 — Ensemble terminology accuracy (frontend)
- **Status:** ✅ PASS
- **Validated by:** M007-l7y6at/S02
- **Evidence files:** i18n terminology corrected across en.json/vi.json. Zero ML model references.
- **Notes:** R022 covers frontend terminology accuracy; R009 covers backend implementation proof.

### R023 — Feature extractor computes 6 features real-time
- **Status:** ✅ PASS
- **Validated by:** M006-doudmh/S02 + S05
- **Evidence files:** ScoreBreakdown exposes all 8 fields. 55 unit tests + E2E response shape validation.
- **Key files:** `agents/ml/feature_extractor.py`

### R024 — Score breakdown JSON per place
- **Status:** ✅ PASS
- **Validated by:** M006-doudmh/S04 + S05
- **Evidence files:** AlgorithmShowcase renders 7 bar chart elements matching ScoreBreakdown keys. Bilingual labels verified. 14/14 build contracts pass.

### R025 — AlgorithmShowcase interactive bar chart
- **Status:** ✅ PASS
- **Validated by:** M006-doudmh/S05
- **Evidence files:** Chat place intent returns re-ranked PlaceResult with final_score, score_breakdown, rank. E2E tests verify card rendering.

### R026 — Admin dashboard at /admin with JWT-protected endpoints
- **Status:** ❌ FAIL
- **Evidence files:** No frontend /admin route exists. Only POST /admin/embed on backend with zero auth. No eval/trigger, traces, or ingest endpoints.
- **Key files:** None exist yet. `backend/app/middleware/auth.py` has JWT pattern to reuse.
- **Gap:** Full admin dashboard + 3 backend endpoints + JWT auth + browser E2E all need implementation.
- **What's needed:** M010/S06 (backend endpoints + JWT) + M010/S07 (frontend dashboard).

### R027 — E2E browser test for auth lifecycle
- **Status:** ❌ FAIL
- **Evidence files:** Auth backend routes exist (register/login/verify-email/resend-otp/me). Frontend auth pages exist. But zero E2E tests for auth flow.
- **Key files:** `backend/app/routers/auth.py`, `frontend/src/components/auth/login-form.tsx`, `register-form.tsx`, `verify-email-form.tsx`
- **Gap:** Need browser E2E test: register → verify (mocked OTP) → login → access protected route. No mocked SMTP/OTP test exists.
- **What's needed:** M010/S07 — browser E2E with mocked OTP verification.

### R028 — Chat UX production polish
- **Status:** ❌ FAIL
- **Evidence files:** Chat interface exists with retry action. Message bubbles exist. But no welcome screen with suggested prompts, no copy action, streaming typing animation status unclear.
- **Key files:** `frontend/src/components/chat/chat-interface.tsx`, `message-bubble.tsx`
- **Gap:** Welcome screen, suggested prompts, copy action, typing animations, improved error surfaces, landing/map/architecture micro-interactions.
- **What's needed:** M010/S05 — Chat UX polish using frontend-design skill.

---

## Fail Requirements Summary

| Requirement | Verdict | What's Needed | Owning Slice |
|---|---|---|---|
| **R010** | FAIL — no unified 5-axis audit | Comprehensive audit script, semantic cache, RAGAS pipeline, fairness audit | M010/S02–S04 |
| **R011** | FAIL — auth not wired | JWT middleware on admin routes + 3 new endpoints | M010/S06 |
| **R026** | FAIL — no admin dashboard code | Full /admin frontend + JWT-protected backend endpoints | M010/S06 |
| **R027** | FAIL — no E2E auth tests | Browser E2E test with mocked OTP for full auth lifecycle | M010/S07 |
| **R028** | FAIL — UX gaps | Welcome screen, suggested prompts, copy action, typing animations, micro-interactions | M010/S05 |

---

## Credential-Blocked Requirements Summary

| Requirement | Verdict | What's Blocked | Unblocking Condition |
|---|---|---|---|
| **R007** | CREDENTIAL_BLOCKED | Live Qdrant embedding proof, RAGAS evaluation | OPENAI_API_KEY + running Qdrant instance |
| **R008** | CREDENTIAL_BLOCKED | Live Google Places API proof, Routes API live test | Google Places API key + Routes API key |

---

## Milestone Validation Reference

| Requirement | Validating Milestone | Status |
|---|---|---|
| R001 | M002-6yge5y/S01 + S04 | ✅ |
| R002 | M002-6yge5y/S02 + S04 | ✅ |
| R003 | M002-6yge5y/S04 | ✅ |
| R004 | M002-6yge5y/S03 + S04 | ✅ |
| R005 | M002-6yge5y/S04 | ✅ |
| R006 | M004/S05 | ✅ |
| R007 | M009-arwc9e/S02 | 🔒 credential_blocked |
| R008 | M005-muzhoo/S02 + S04 | 🔒 credential_blocked |
| R009 | M006-doudmh/S02 + S03 + S05 | ✅ |
| R010 | — | ❌ fail |
| R011 | — | ❌ fail |
| R012 | — | ⏭️ out-of-scope |
| R013 | M009-arwc9e/S01 | ✅ |
| R014 | M004/S05 | ✅ |
| R015 | M009-arwc9e/S03 | ✅ |
| R016 | M004/S05 | ✅ |
| R017 | M005-muzhoo/S02 | ✅ |
| R018 | M005-muzhoo/S02 | ✅ |
| R019 | M005-muzhoo/S03 | ✅ |
| R020 | M005-muzhoo/S04 | ✅ |
| R021 | M005-muzhoo/S03 | ✅ |
| R022 | M007-l7y6at/S02 | ✅ |
| R023 | M006-doudmh/S02 + S05 | ✅ |
| R024 | M006-doudmh/S04 + S05 | ✅ |
| R025 | M006-doudmh/S05 | ✅ |
| R026 | — | ❌ fail |
| R027 | — | ❌ fail |
| R028 | — | ❌ fail |

---

## Implementation Landscape

### Test Suite Status
- **Backend:** 550 tests across 24 test files (exceedes 230+ threshold)
- **Frontend:** 9 test files (8 .mjs + 1 .ts)

### Key Implementation Files Verified
| File | Purpose |
|---|---|
| `backend/app/routers/admin.py` | POST /admin/embed (only admin endpoint) |
| `backend/app/middleware/auth.py` | JWT auth pattern (reusable for admin) |
| `backend/app/routers/chat.py` | Chat endpoint |
| `backend/app/routers/auth.py` | Auth endpoints (register, login, verify, OTP) |
| `agents/guardrails/grounded_answer.py` | Grounded answer composition + no-evidence |
| `agents/graph/agent_service.py` | Agent orchestration with session memory |
| `agents/ml/ensemble_reranker.py` | 3-tree Bagging ensemble |
| `agents/ml/feature_extractor.py` | 6-feature real-time extraction |
| `agents/tools/places_service.py` | Google Places API (New) client |
| `agents/tools/qdrant_service.py` | Qdrant vector DB client |
| `agents/tools/embedding_service.py` | OpenAI embedding service |
| `agents/tools/proposition_chunker.py` | RAG proposition chunker |
| `backend/app/services/langfuse_service.py` | Observability tracing |
| `frontend/src/components/chat/chat-interface.tsx` | Chat UI component |
| `frontend/src/components/map/place-proof-map.tsx` | Map display component |

---

*Audit produced by M010/S01. This document is the single inspection surface for requirement status across the project. Future agents should update this file when requirements are validated or remediated.*
