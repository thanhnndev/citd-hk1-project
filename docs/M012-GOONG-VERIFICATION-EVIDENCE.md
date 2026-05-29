# M012 Goong Verification Evidence

## Scope

This document is the durable audit surface for the Goong-only provider verification gates after S05 cleanup. It separates mocked backend regression proof, frontend map/build proof, and live Goong provider status without exposing credentials or raw upstream payloads.

Current evidence proves:

- Backend Goong contracts pass under mocked/regression tests.
- Frontend Goong map contract and production build pass without exposing backend `GOONG_API_KEY` to the browser.
- The live verifier reports a sanitized terminal `RESULT=` status.
- Missing/fake/placeholder credentials are documented as `credential_blocked`, not as live provider success.
- The S05 zero-reference gate passes across active code, tests, current docs, config, and dependency manifests while excluding generated/vendor/cache paths and immutable `data/` corpus files.

Out of scope for this evidence package:

- Historical milestone audit records may describe prior provider migrations, but active code/config/docs use Goong-only provider instructions.
- Claiming browser live tile rendering unless a browser/server/public map-token gate is explicitly run.
- Publishing Goong keys, raw Places payloads, or raw Routes payloads.

## Backend Mocked Gate

Status: passed.

Command:

```bash
cd /home/thanhnndev/develop/projects/citd-hk1-project/backend && pytest -q tests/test_config.py tests/test_places_models.py tests/test_places_service.py tests/test_routes_service.py tests/test_place_recommendation_service.py tests/test_place_recommendation_reranking.py tests/test_agent_place_recommendations.py tests/test_verify_goong_live.py --tb=short
```

Outcome:

- Exit code: 0
- Result: 92 passed in 2.68s
- Evidence source: `.gsd/milestones/M012-4ucdfp/slices/S04/tasks/T02-SUMMARY.md`
- Notes: This gate uses mocked/regression coverage and does not require live Goong credentials.

## Frontend Contract And Build Gate

Status: passed.

Command:

```bash
cd frontend && node --test tests/s03-map-proof-contract.test.mjs && bun run build
```

Outcome:

- Exit code: 0
- Result: static map contract passed and Next.js production build completed successfully.
- Evidence source: `.gsd/milestones/M012-4ucdfp/slices/S04/tasks/T03-SUMMARY.md`
- Notes: The contract verifies the browser map component uses only `NEXT_PUBLIC_GOONG_MAPTILES_KEY`, does not read `GOONG_API_KEY`, and does not fetch backend-owned Places data directly.
- Known non-blocking issue: build stderr included Node deprecation warning `[DEP0205] module.register() is deprecated`.

## Live Verifier Behavior

Verifier: `scripts/verify-goong-live.py`

Contract:

- Uses `GOONG_API_KEY` as the sole Goong provider credential for Places and Routes verification.
- Treats missing, fake, and placeholder key values as blocked credentials with exit code 0 and terminal `RESULT=credential_blocked`.
- Prints sanitized phase diagnostics only: `CONFIG`, `PLACES_RESPONSE`, `CANDIDATES`, `ROUTES_RESPONSE`, `RESULT`, and sanitized `ERROR`/`VALIDATION_ERRORS` when applicable.
- Does not print API keys or raw upstream provider payloads.
- Reports `RESULT=passed` only after normalized coordinate-bearing Places candidates and at least one successful Routes metric are validated.

Focused verifier contract command:

```bash
cd backend && pytest -q tests/test_verify_goong_live.py --tb=short
```

Outcome:

- Exit code: 0
- Result: passed.
- Evidence source: `.gsd/milestones/M012-4ucdfp/slices/S04/tasks/T01-SUMMARY.md`

## Credentialed Live Result

Status: credential_blocked.

Fresh command run for this evidence package:

```bash
python3 scripts/verify-goong-live.py
```

Outcome:

- Exit code: 0
- Terminal result: `RESULT=credential_blocked`
- Sanitized status: `goong_api_key_status` was `missing`.
- Evidence run: `.gsd/exec/a0ba18ec-a032-4b7a-ae86-8f8c71aeb19c.stdout`

Sanitized output excerpt:

```text
CONFIG={"goong_api_key_status": "missing", "location_bias": {"lat": 10.1835208, "lng": 104.0496843}, "max_places_result_count": 5, "max_route_destinations": 3, "query_language": "vi"}
RESULT={"rerun": "export GOONG_API_KEY=<valid key>; python3 scripts/verify-goong-live.py", "status": "credential_blocked"}
RESULT=credential_blocked
```

Interpretation:

- This is blocked-live proof, not live provider success.
- No real `GOONG_API_KEY` was available to this run.
- No fake or placeholder key is cited as success.
- A future credentialed proof may update this section only if `GOONG_API_KEY` is real and the verifier exits with terminal `RESULT=passed`.

## Optional Browser Live Proof

Status: not run.

Reason:

- The completed frontend gate covered static browser contract and production build.
- No browser/server/public map-token live tile gate was run during T04.

Interpretation:

- This document does not claim live browser tile rendering proof.
- Any future browser live proof must record the exact server/browser command, public map token status, and sanitized outcome separately.

## S05 Cleanup Status

S05 cleanup updates active documentation, config, tests, and requirement evidence to use Goong-only provider instructions. The closeout gate the S05 zero-reference script under `scripts/` scans active repository text and reports exact path/line diagnostics for stale provider references. It excludes generated/cache/vendor paths and immutable `data/` corpus files, where crawled source text may be preserved verbatim without weakening the active code/tests/docs/config/dependency gate.

Fresh closeout command:

```bash
REDIS_URL=memory:// RATE_LIMIT_CHAT=10000/minute python3 scripts/verify-s05-zero-<legacy-provider>-references.py && cd backend && pytest -q tests/test_places_models.py tests/test_places_service.py tests/test_routes_service.py tests/test_place_recommendation_service.py tests/test_place_recommendation_reranking.py tests/test_agent_place_recommendations.py tests/test_chat_api.py tests/test_verify_goong_live.py --tb=short && cd ../frontend && node --test tests/s03-map-proof-contract.test.mjs tests/s05-chat-e2e.test.mjs && bun run build && cd .. && python3 scripts/verify-goong-live.py
```

Outcome:

- Exit code: 0
- Zero-reference gate: `RESULT=passed`
- Backend mocked regression: 134 passed
- Frontend contract/E2E/build: passed
- Live Goong verifier: `RESULT=credential_blocked` with missing credentials
- Evidence run: `.gsd/exec/79ed2f01-83cd-48f5-9d6f-59c95bcb0068.stdout`

This document remains the human-readable audit surface for mocked regression, frontend build/contract, zero-reference closeout, and credential-aware live verifier status.

## Verification Evidence

| # | Command | Exit Code | Verdict | Duration |
|---|---------|-----------|---------|----------|
| 1 | `cd backend && pytest -q tests/test_verify_goong_live.py --tb=short` | 0 | pass | 6069ms |
| 2 | `cd /home/thanhnndev/develop/projects/citd-hk1-project/backend && pytest -q tests/test_config.py tests/test_places_models.py tests/test_places_service.py tests/test_routes_service.py tests/test_place_recommendation_service.py tests/test_place_recommendation_reranking.py tests/test_agent_place_recommendations.py tests/test_verify_goong_live.py --tb=short` | 0 | pass, 92 passed | 6853ms |
| 3 | `cd frontend && node --test tests/s03-map-proof-contract.test.mjs && bun run build` | 0 | pass | 13341ms |
| 4 | `python3 scripts/verify-goong-live.py` | 0 | pass, credential_blocked without credentials | 489ms |
| 5 | `REDIS_URL=memory:// RATE_LIMIT_CHAT=10000/minute python3 scripts/verify-s05-zero-<legacy-provider>-references.py && cd backend && pytest -q tests/test_places_models.py tests/test_places_service.py tests/test_routes_service.py tests/test_place_recommendation_service.py tests/test_place_recommendation_reranking.py tests/test_agent_place_recommendations.py tests/test_chat_api.py tests/test_verify_goong_live.py --tb=short && cd ../frontend && node --test tests/s03-map-proof-contract.test.mjs tests/s05-chat-e2e.test.mjs && bun run build && cd .. && python3 scripts/verify-goong-live.py` | 0 | pass, S05 closeout gate complete with credential_blocked live boundary | 51874ms |

## Final S04 Status

- Backend mocked regression gate: passed.
- Frontend contract/build gate: passed.
- Live Goong verifier: credential_blocked due to missing real `GOONG_API_KEY`.
- Credential leak check: no credentials included in this document.
- S05 cleanup boundary: active docs now use Goong-only provider wording; credentialed live proof still requires terminal `RESULT=passed`.
