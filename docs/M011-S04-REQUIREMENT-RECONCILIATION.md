# M011 S04 Requirement Reconciliation Matrix

**Milestone:** M011-uzype3  
**Slice:** S04 - GSD Requirement Reconciliation  
**Status:** Evidence contract for S04/S05; do not mark credential-blocked or deferred work as complete.

## Scope

This matrix maps active `.gsd/REQUIREMENTS.md` items to the safest reconciliation action after the S02 audit and S03 bounded fixes. It is documentation and diagnostic input only; it does not implement product features, mutate `.gsd/REQUIREMENTS.md`, or replace S05 verification.

Current code/tests outrank stale milestone prose when they conflict. Mocked tests, static inspection, and prior summaries can support implementation status, but live OpenAI, Google, Qdrant, Langfuse, RAGAS CI/CD, semantic cache, production fairness history, and frontend performance/accessibility claims remain unproven until credentialed or environment-appropriate evidence exists.

## Reconciliation Rules

- `validate`: Move or keep a requirement as validated only when concrete tracked code, tests, scripts, or durable milestone evidence directly prove the behavior.
- `keep_active`: Keep the requirement active when the capability is partially implemented, still needs S05 verification, or includes unbuilt pieces.
- `defer`: Keep explicit follow-up scope for major unbuilt or credential-blocked capabilities rather than silently marking them met.
- `out_of_scope`: Use only when the audited item is not an atomic product behavior; do not use it to hide product gaps.
- `credential_blocked`: Preserve this label for live OpenAI, Google, Qdrant, and Langfuse proof until valid credentials/services are available.

## Caveat Register

| Caveat | Applies To | Required Language |
|---|---|---|
| `credential_blocked` | OpenAI embeddings, RAGAS, Google Places/Routes, Qdrant, Langfuse, full live workflow | Local evidence is useful, but live proof needs valid credentials, running services, and network access. |
| `deferred_major_scope` | RAGAS CI/CD, Redis semantic cache, admin dashboard polish, chat polish, production audit history | Major missing subsystems become follow-up work; Redis semantic-cache production behavior is not validated by static docs. |
| `missing_operational_metrics` | Fairness history, trace retention, cultural accuracy, displacement mitigation | Local snapshots/tests do not equal production monthly fairness history or durable operational metrics. |
| `frontend_nonfunctional_pending` | FCP, WCAG, responsive/accessibility regression, polished UX | Prior evidence may drift; S05 must run fresh frontend verification where practical. |
| `endpoint_naming_drift` | Admin eval/traces/ingest wording | Current source owns route names; stale `/admin/eval` prose must not override `POST /admin/eval/trigger`. |

## Active Requirement Matrix

| Requirement | Planned Action | Evidence Paths | Caveats | S05 Implication |
|---|---|---|---|---|
| R007 | `keep_active` with partial validation notes | `.gsd/REQUIREMENTS.md`; `docs/M011-REQUIREMENTS-AUDIT.md`; `backend/app/routers/admin.py`; `scripts/verify-embedding-idempotency.py`; `backend/tests/test_embedding_search.py` | OpenAI embeddings and Qdrant live ingestion remain `credential_blocked`; RAGAS CI/CD is `deferred_major_scope`. Do not cite mocked/static tests as live `/admin/embed` or RAGAS success. | Run strongest practical embedding/RAG checks; record credential-blocked status if no valid `OPENAI_API_KEY` or Qdrant service is available. |
| R008 | `keep_active` | `.gsd/REQUIREMENTS.md`; `docs/M011-REQUIREMENTS-AUDIT.md`; `agents/tools/places_service.py`; `agents/tools/routes_service.py`; `scripts/verify-google-places-live.py` | Google Places API and Routes matrix live proof remain `credential_blocked` until valid Google credentials and enabled APIs are available. | S05 may run static/mocked tests locally, but must not mark live Places/Routes verified without `RESULT=passed` from live verification. |
| R010 | `keep_active` and `defer` missing subsystems | `.gsd/REQUIREMENTS.md`; `docs/M011-REQUIREMENTS-AUDIT.md`; `scripts/verify-m011-s03-bounded-fixes.mjs`; `backend/tests/test_admin_traces_endpoint.py`; `backend/tests/test_fairness_audit.py` | Guardrails, grounding, auth, traces status, and local fairness surfaces have evidence; semantic cache, RAGAS CI/CD, unified audit, monthly production fairness history, and live Langfuse proof remain `deferred_major_scope`, `missing_operational_metrics`, or `credential_blocked`. | Verify deterministic tests and keep all missing compliance subsystems active/deferred rather than validated. |
| R011 | `keep_active` with route-name reconciliation | `.gsd/REQUIREMENTS.md`; `backend/app/routers/admin.py`; `backend/tests/test_admin_eval_endpoint.py`; `backend/tests/test_admin_stats_endpoint.py`; `backend/tests/test_admin_traces_endpoint.py`; `backend/tests/test_admin_embed_auth.py`; `scripts/verify-m011-s03-bounded-fixes.mjs` | Current source uses `POST /admin/eval/trigger`, `GET /admin/traces`, `GET /admin/stats`, `GET /admin/fairness`, and `POST /admin/embed` with JWT. `/admin/ingest` remains unimplemented or represented by `/admin/embed`, so stale wording must be reconciled carefully. | S05 should run targeted admin tests and avoid reintroducing stale `POST /admin/eval` naming. |
| R013 | `validate` if status reconciliation cites existing corpus evidence | `.gsd/REQUIREMENTS.md`; `data/tourism_documents.jsonl`; `data/eval_dataset.jsonl`; `scripts/ingest_propositions.py`; `backend/tests/test_proposition_chunker.py`; `backend/tests/test_proposition_ingestion.py`; `backend/tests/test_corpus.py` | Corpus normalization is deterministic and not credential-blocked. Keep wording scoped to corpus/chunk/citation metadata, not live RAG quality. | S05 can optionally rerun corpus tests, but no live provider proof is required for this requirement itself. |
| R015 | `validate` or keep validated evidence scoped to honest grounded answers | `.gsd/REQUIREMENTS.md`; `agents/guardrails/grounded_answer.py`; `agents/graph/agent_service.py`; `backend/tests`; `docs/M011-REQUIREMENTS-AUDIT.md` | Static/code tests can prove citation/no-evidence behavior; broader cultural/map/restaurant/fairness quality still depends on live providers and metrics. | Run practical backend/agent tests and avoid expanding validation to unmeasured cultural accuracy or operational fairness outcomes. |
| R026 | `keep_active` | `.gsd/REQUIREMENTS.md`; `frontend/src/app/[locale]/admin/page.tsx`; `frontend/src/lib/admin-api.ts`; `frontend/src/app/api/admin/route.ts`; `backend/app/routers/admin.py`; `frontend/tests/s07-auth-e2e.test.mjs` | Admin route/client surfaces exist, but full authenticated dashboard UX, ingestion semantics, eval result quality, trace observability, and frontend accessibility/performance remain `frontend_nonfunctional_pending` or `credential_blocked` for Langfuse/RAGAS. | S05 should run frontend/build/admin checks where practical and report any credential-blocked trace/eval proof honestly. |
| R028 | `keep_active` | `.gsd/REQUIREMENTS.md`; `frontend/src/app/[locale]/chat/page.tsx`; `frontend/tests/s07-auth-e2e.test.mjs`; `docs/M010-CLOSEOUT-EVIDENCE.md` | Prior E2E evidence supports core chat UX, but welcome screen, suggested prompts, copy/retry actions, typing animations, and current frontend performance/accessibility are still pending. | S05 owns current frontend verification; do not validate polish or nonfunctional claims from stale evidence alone. |
| R029 | `validate` after S01/S02/S03/S04 artifacts exist | `.gsd/REQUIREMENTS.md`; `docs/M011-S01-REQUIREMENTS-EVIDENCE-INVENTORY.md`; `docs/M011-REQUIREMENTS-AUDIT.md`; `scripts/verify-m011-s01-inventory.mjs`; `scripts/verify-m011-s02-audit.mjs`; `scripts/verify-m011-s03-bounded-fixes.mjs`; `scripts/verify-m011-s04-reconciliation.mjs` | This is an audit-process requirement, not a product feature. Validation should cite coverage artifacts and diagnostics only. | S05 can include all M011 verifier scripts in final evidence. |
| R031 | `validate` for bounded S03 fixes only; keep major gaps deferred | `.gsd/REQUIREMENTS.md`; `docs/M011-REQUIREMENTS-AUDIT.md`; `scripts/verify-m011-s03-bounded-fixes.mjs`; admin/fairness tests listed in S03 evidence | Bounded fixes were limited to route/auth diagnostics, frontend/static version drift notes, and fairness local aggregation. Major live-provider, RAGAS CI/CD, semantic cache, and production metrics remain deferred. | S05 should distinguish bounded remediation success from full product completion. |
| R032 | `validate_after_reconciliation_evidence` | `.gsd/REQUIREMENTS.md`; `docs/M011-S04-REQUIREMENT-RECONCILIATION.md`; `scripts/verify-m011-s04-reconciliation.mjs`; `docs/M011-REQUIREMENTS-AUDIT.md` | R032 is not validated by intention alone. It becomes validated only after this matrix and verifier exist and `.gsd/REQUIREMENTS.md` reconciliation follows concrete evidence. | S05 should check the reconciled statuses against this matrix and fail drift if unsupported claims are introduced. |
| R033 | `keep_active` for S05 | `.gsd/REQUIREMENTS.md`; `docs/M011-REQUIREMENTS-AUDIT.md`; `scripts/verify-m011-s04-reconciliation.mjs` | R033 explicitly remains active because strongest practical verification is owned by S05. Credential-blocked checks must be recorded honestly with `credential_blocked` for OpenAI, Google, Qdrant, and Langfuse. | S05 must run and record the strongest local suite; S04 must not pre-validate it. |
| R034 | `validate_after_reconciliation_evidence` with explicit deferrals | `.gsd/REQUIREMENTS.md`; `docs/M011-S04-REQUIREMENT-RECONCILIATION.md`; `docs/M011-REQUIREMENTS-AUDIT.md` | R034 is only validated when major unbuilt capabilities are named as active/deferred follow-up work: RAGAS CI/CD, semantic cache, live provider proof, production fairness history, and frontend nonfunctional proof, not silently closing major gaps. | S05 should preserve follow-up language and avoid silently closing major gaps. |

## S05 Readiness Notes

- R033 remains active for S05 verification. S04 only supplies the drift-checking contract.
- R032 and R034 should not be marked validated until reconciliation evidence exists and caveats remain intact.
- Credential-blocked live checks must name the blocker and unblock condition instead of becoming pass/fail claims.
- Frontend performance/accessibility and production fairness history need fresh evidence; prior summaries are not enough.
- Admin route reconciliation should use current `backend/app/routers/admin.py` and tests as the source of truth.
