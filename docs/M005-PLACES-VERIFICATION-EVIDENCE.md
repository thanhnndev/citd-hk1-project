# M005 Places Verification Evidence

> **Milestone:** M005-muzhoo · **Slice:** S04 · **Date:** 2025-05-19
> **Purpose:** Durable, inspectable record of what passed, what was mocked, and whether live Google Places proof passed or was credential-blocked.

---

## Scope

S04 is the verification slice for M005. It packages proof that:

1. Mocked backend Places contracts handle failure/ownership/negative states truthfully.
2. Frontend ownership checks and map safe-state proofs are static/offline (no browser-side Google Places lookup).
3. The live Google Places verifier either passes with normalized candidates (`RESULT=passed`) or exits as `RESULT=credential_blocked` when credentials are absent/unusable.
4. **Redaction boundary:** never print API keys, raw provider payloads, or secrets in any output.

This document **does not** re-scope S01–S03 behavior or claim live proof from mocked tests.

---

## 1. Mocked Backend Proof

### Tests Run

```bash
cd backend && pytest tests/test_places_models.py tests/test_places_service.py \
  tests/test_agent_place_recommendations.py tests/test_chat_endpoint.py \
  tests/test_sse_stream.py -q
```

### Result: **53 passed, 5 warnings**

| Category | File | Coverage |
|----------|------|----------|
| Place model validation | `test_places_models.py` | Validation rules, schema shapes |
| Places service contracts | `test_places_service.py` | Failure states, error envelopes, no-secret negative responses |
| Agent place recommendations | `test_agent_place_recommendations.py` | Server-side ownership, recommendation fallbacks |
| Chat endpoint validation | `test_chat_endpoint.py` | Request validation, language handling |
| SSE stream | `test_sse_stream.py` | Stream format, failure tokens |

**Nature of proof:** Mocked/deterministic. These tests use in-memory fixtures and do not call external APIs. They verify that the backend contracts produce truthful `PlaceToolResponse` status/error envelopes and `ChatResponse` places/fallback/reasoning_log structures for all negative states.

---

## 2. Frontend Ownership / Map Proof

### Tests Run (package-local)

```bash
cd frontend && node --test tests/s04-build-contract.test.mjs tests/s03-map-proof-contract.test.mjs
```

**Result: 19 passed** — validates build output routes, contentinfo/nav/section elements, lang attributes, and no console.error/warn in production build.

### Tests Run (root wrapper)

```bash
node --test tests/s03-map-proof-contract.test.mjs
```

**Result: 5 passed** — validates that frontend source/tests do not own browser-side Google Places lookup, and map message catalogs include matching non-empty proof-surface keys.

### Lint

```bash
npm run lint
```

**Result: passed** — no ESLint violations.

**Nature of proof:** Static/offline. Frontend ownership checks verify that browser-side Google Places lookups are NOT implemented; all Places resolution is server-side.

---

## 3. Live-or-Credential-Blocked Verifier

### Script

`scripts/verify-google-places-live.py`

### How it works

1. Imports the backend Places service directly and constructs a `Settings` instance with a harmless OpenAI placeholder (so missing unrelated OpenAI credentials cannot mask Google Places credential status).
2. Checks the Google API key for presence, length, and obvious placeholder patterns.
3. If the key looks present: makes one Vietnamese (Hàm Ninh) text search to Google Places API and validates normalized candidates (place_id, display_name, location or Google Maps URI).
4. If the key is missing/fake/placeholder: skips the provider call entirely.
5. Emits JSON-labelled `CONFIG` / `RESULT` lines and a final `RESULT=<label>` line.

### RESULT Labels

| Label | Meaning | Exit Code |
|-------|---------|-----------|
| `RESULT=passed` | Live provider returned normalized candidates matching the query | 0 |
| `RESULT=credential_blocked` | Key is missing, fake, or placeholder — no provider call made | 0 |
| `RESULT=failed` | Key appears present but provider returned empty/auth/quota/malformed response | 1 (nonzero) |

**Critical distinction:** `credential_blocked` ≠ `failed`. The former means we never called the provider (no quota consumed); the latter means we called it and it did not return valid data.

### Command: No Key (blank)

```bash
GOOGLE_PLACES_API_KEY= python3 scripts/verify-google-places-live.py
```

**Output:**
```
CONFIG={"google_places_api_key_status": "missing", "location_bias": {"lat": 10.1794, "lng": 104.0491}, "max_result_count": 5, "query_language": "vi"}
RESULT={"rerun": "export GOOGLE_PLACES_API_KEY=<valid key>; python3 scripts/verify-google-places-live.py", "status": "credential_blocked"}
RESULT=credential_blocked
```

**Result: ✅ `RESULT=credential_blocked` (exit 0)**

### Command: Fake Key (redaction check)

```bash
GOOGLE_PLACES_API_KEY='fake-secret-do-not-print' python3 scripts/verify-google-places-live.py
```

**Redaction check:** grep for `fake-secret-do-not-print` in output → **0 matches** (key is NOT printed).

**Result: ✅ Redaction boundary held — credential value not leaked.**

### Live Proof Status

**Live `RESULT=passed` was not exercised** because no real Google Places API key was available. This is expected in CI/autonomous environments; re-run with a valid key to obtain live proof.

---

## 4. Redaction Policy

The following are **never** printed in any S04 output:

- API key values (Google Places, OpenAI, or any provider)
- Raw provider response bodies (HTTP response JSON/XML)
- Authentication tokens, headers, or secrets

The verifier script and all test suites adhere to this boundary. Redaction is verified by the fake-key grep check above (Section 3).

---

## 5. Final Closeout Commands

| # | Command | Result | Notes |
|---|---------|--------|-------|
| 1 | `GOOGLE_PLACES_API_KEY= python3 scripts/verify-google-places-live.py` | ✅ `RESULT=credential_blocked`, exit 0 | Blank key — no provider call |
| 2 | Fake-key redaction grep | ✅ 0 matches | Credential value not leaked |
| 3 | `cd backend && pytest ...` (5 test files) | ✅ 53 passed, 5 warnings | Mocked backend contracts |
| 4 | `cd frontend && node --test tests/s04-build-contract.test.mjs tests/s03-map-proof-contract.test.mjs` | ✅ 19 passed | Frontend build/contract proof |
| 5 | `node --test tests/s03-map-proof-contract.test.mjs` | ✅ 5 passed | Root ownership/map proof |
| 6 | `npm run lint` | ✅ passed | No ESLint violations |

---

## 6. Requirement Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| R020 (Places failure handling) | ✅ Closed | Sections 1–3 above |
| R008 (Backend contract integrity) | ✅ Supported | Section 1: 53 backend tests |
| R021 (Frontend safe states) | ✅ Supported | Section 2: 24 frontend contract tests |

---

## 7. Known Gaps

- **Live proof (`RESULT=passed`)** requires a valid Google Places API key. Re-run the verifier script with `GOOGLE_PLACES_API_KEY=<valid key>` to obtain live proof.
- Deprecation warnings from FastAPI/Pydantic test suite (5 warnings) do not affect correctness; tracked separately.
