# M014/S06 Integrated UX Closeout

**Result:** `credential_blocked`
**Date:** 2026-06-01T03:18:32Z
**Verifier:** `scripts/verify-m014-s06-integrated-ux.py`

---

## Commands

```bash
# Single-command closeout verification:
python3 scripts/verify-m014-s06-integrated-ux.py

# Individual phases:
python3 -m pytest backend/tests/test_m014_s06_integrated_chat_api.py -v --tb=short -x
cd frontend && timeout 240 node --test --test-concurrency=1 tests/s06-integrated-chat-ux.test.mjs
cd frontend && timeout 60 node --test tests/s04-explainability-contract.test.mjs
cd frontend && timeout 60 node --test tests/s05-messenger-chat-contract.test.mjs
python3 scripts/verify-m014-s02-google-places-primary.py
python3 scripts/verify-m014-s03-recommendation-explanation.py
cd frontend && npx tsc --noEmit
cd frontend && npx next build
```

---

## Evidence Matrix (R052–R056)

| Requirement | Description | Evidence Source | Status |
|-------------|-------------|-----------------|--------|
| R052 | Recommendation with score + explanation | S06 API tests (29 tests), S03 verifier, S06 browser test | ✅ |
| R053 | Explainability UI (score axes, provider labels) | S04 contract tests (28+ tests), S03 verifier | ✅ |
| R054 | Thinking/status timeline (streaming + post-response) | S04 contract tests, S06 browser test (status retention) | ✅ |
| R055 | Messenger chat UX (left/right bubbles, quick replies, responsive) | S05 contract tests (30+ tests), S06 browser test (viewport, keyboard, chips) | ✅ |
| R056 | Contextual follow-up without RAG fallback | S06 API tests (follow-up intent), S06 browser test (no RAG wording) | ✅ |

---

## Phase Results

| Status | Phase | Verdict | Duration |
|--------|-------|---------|----------|
| ✅ | S06 API Contract Tests | `passed` | 8491ms |
| ✅ | S06 Browser UX Tests | `passed` | 33918ms |
| ✅ | S04 Explainability Contract Tests | `passed` | 172ms |
| ✅ | S05 Messenger Chat Contract Tests | `passed` | 163ms |
| ⚠️ | S02 Google Places Verifier | `credential_blocked` | 0ms |
| ✅ | S03 Recommendation Explanation Verifier | `passed` | 38652ms |
| ✅ | TypeScript Type-Check | `passed` | 1962ms |
| ✅ | Next.js Build | `passed` | 13511ms |

**Summary:** 7 passed, 0 failed, 1 credential-blocked

---

## Provider Credential Caveats

| Provider | Credential | Status | Impact |
|----------|-----------|--------|--------|
| Google Places | `GOOGLE_PLACES_API_KEY` | Not set — live verification skipped | S02 verifier classifies as `credential_blocked` when missing; local contract tests still pass |
| OpenAI / LLM | `OPENAI_API_KEY` | Not set — live provider calls skipped | Backend API tests use local fixtures; no live LLM calls in test suite |
| Langfuse | `LANGFUSE_SECRET_KEY` | Not set — tracing disabled | Tracing optional; does not block local verification |

**Rule:** When credentials are missing, the verifier classifies live-only phases as `credential_blocked` and exits 0 (not a failure). This is intentional — the closeout proves local contract integrity, not live provider availability.

---

## No-Frontend-Fabrication Proof

The following negative checks confirm the frontend does NOT fabricate reasoning or
place data without backend support:

1. **S05 contract test**: Verifies quick reply chips are NOT LLM/network-derived —
   checks that `prompts` array is not sourced from `streamChat`, `sendChat`, or
   `response.prompts`.
2. **S04 contract test**: Verifies `PlaceCard` does not contain hardcoded rationale
   patterns like "because this place" or "we recommend this".
3. **S06 browser test (Negative: API error)**: When API returns 500, the UI shows
   an error state and does NOT render fabricated place recommendations.
4. **S06 browser test (Negative: Empty places)**: When `places` array is empty,
   no "Recommended Places" section renders.
5. **S06 browser test (Negative: Missing explanation)**: When `explanation` field
   is absent, place name still renders but no fake `primary_reason` text appears.

---

## Contextual Follow-Up / No RAG Fallback Proof

1. **S06 API test**: `test_followup_contextual_intent` — verifies the backend
   recognizes follow-up intent and reuses prior context (intent=`followup_contextual`,
   `fallback=false`, session_id preserved).
2. **S06 browser test**: `test_followup_question_reuses_prior_context` — sends a
   second question ("Why did you recommend this place?") and asserts:
   - Follow-up question appears in conversation history
   - Response does NOT contain RAG/fallback wording ("I don't have enough",
     "I couldn't find", "let me search")
   - At least 2 user message bubbles present after follow-up

---

## Responsive UX Proof

1. **S05 contract tests**: Verifies responsive breakpoints (`md:`, `sm:`), `100dvh`
   mobile viewport height, and responsive `max-width` on message bubbles.
2. **S06 browser test (viewport)**: Runs at 375×812 (mobile) and 1280×800 (desktop).
   Asserts no horizontal overflow on mobile (`scrollWidth <= viewportWidth + 10`).
3. **S06 browser test (keyboard accessibility)**: Verifies Enter sends messages,
   Tab moves focus, and textarea accepts keyboard input.
4. **S06 browser test (negative: mobile overflow)**: Explicitly checks
   `bodyScrollWidth <= viewportWidth` after sending a recommendation at mobile size.

---

## Redaction Constraints

The verifier script and all test files follow these redaction rules:

1. **No secret echoing**: API keys, tokens, and credentials are never printed to
   stdout/stderr. The verifier's `redact()` function strips patterns like
   `AIza*`, `sk-*`, and `ghp_*` from any logged output.
2. **Test fixtures use synthetic data**: All browser and API tests use inline
   fixtures with `place_001`, `test-session-001`, and example.com URLs.
3. **No PII in prompts**: Quick reply labels verified not to contain GPS coordinates,
   phone numbers, email addresses, or exact user locations (S05 negative test).
4. **Provider status vocabulary**: Uses canonical values (`ok`, `credentials_blocked`,
   `upstream_error`, `empty`, `unavailable`) — no raw error messages from providers
   leak into the UI.

---

## Remaining Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Live provider availability not proven without credentials | Low | `credential_blocked` exit is documented; CI should run with test keys |
| Browser tests depend on Next.js dev server auto-start | Low | `FRONTEND_URL` env var allows external server; auto-start has 60s timeout |
| Playwright browser binaries required | Medium | `npx playwright install` in CI; cached in `~/.cache/ms-playwright/` |
| Next.js build may fail on stale deps | Low | Full `npm install` before build; type-check catches most issues first |

---

## Files

- `scripts/verify-m014-s06-integrated-ux.py` — orchestrator (this script)
- `backend/tests/test_m014_s06_integrated_chat_api.py` — S06 API contract tests
- `frontend/tests/s06-integrated-chat-ux.test.mjs` — S06 browser UX tests
- `frontend/tests/s04-explainability-contract.test.mjs` — S04 frontend contracts
- `frontend/tests/s05-messenger-chat-contract.test.mjs` — S05 frontend contracts
- `scripts/verify-m014-s02-google-places-primary.py` — S02 Google Places verifier
- `scripts/verify-m014-s03-recommendation-explanation.py` — S03 explanation verifier
- `docs/M014-S02-GOOGLE-PLACES-CONTRACT.md` — S02 evidence doc
- `docs/M014-S03-RECOMMENDATION-EXPLANATION-CONTRACT.md` — S03 evidence doc
- `docs/M014-S04-EXPLAINABILITY-THINKING-UI.md` — S04 evidence doc
- `docs/M014-S05-MESSENGER-CHAT-REDESIGN.md` — S05 evidence doc
