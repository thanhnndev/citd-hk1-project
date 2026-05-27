# M011 Requirements Audit Verdict Report

**Milestone:** M011-uzype3  
**Slice:** S02 - Audit Verdict Report  
**Source inventory:** `docs/M011-S01-REQUIREMENTS-EVIDENCE-INVENTORY.md`  
**Status:** Drafted for downstream S03 remediation and S04 requirement reconciliation.

## Scope

This report converts the S01 evidence inventory into verdicts for every canonical audit ID: REQ-01 through REQ-08, REQ-09A through REQ-09D, and REQ-10 through REQ-14. It audits `docs/REQUIREMENTS.md` against current source files, tracked tests/scripts, and prior milestone evidence already present in the repository.

This task is documentation-only. It does not run credentialed provider calls, alter implementation code, or reconcile `.gsd/REQUIREMENTS.md` statuses. S04 owns status reconciliation; S03 owns bounded fixes or explicit deferrals.

## Verdict Legend

| Token | Meaning |
|---|---|
| `pass` | Deterministic current code, tests, scripts, or durable evidence support the requirement area without material known gaps. |
| `partial` | Some promises are implemented or evidenced, but gaps, stale proof, unverified non-functional claims, or operational omissions remain. |
| `fail` | Current evidence clearly contradicts a promised capability or shows it is missing. |
| `credential_blocked` | The remaining proof requires external credentials/services such as Google, OpenAI, Qdrant, or Langfuse and cannot be honestly executed locally. |
| `out-of-scope` | The item is not actually promised as product behavior by `docs/REQUIREMENTS.md` or is explicitly excluded. |

## Required Caveat Labels

- `credential_blocked`: live Google Places/Routes, OpenAI embedding/RAGAS, Qdrant, or Langfuse proof requires valid credentials and services.
- `endpoint_naming_drift`: endpoint names differ across requirements, prior evidence, and current source/tests; current source is the authority for S04 reconciliation.
- `version_drift`: `docs/REQUIREMENTS.md` version claims may differ from manifests or installed runtime versions.
- `missing_operational_metrics`: deterministic tests exist, but durable production-style metrics or audit history are missing.
- `prior_evidence_may_drift`: M002-M010 evidence is useful but may no longer match current source.

## Executive Summary Counts

| Verdict | Count | Audit IDs |
|---|---:|---|
| `pass` | 3 | REQ-01, REQ-04, REQ-14 |
| `partial` | 10 | REQ-02, REQ-03, REQ-05, REQ-06, REQ-08, REQ-09A, REQ-09B, REQ-09C, REQ-09D, REQ-10 |
| `fail` | 0 | None |
| `credential_blocked` | 3 | REQ-07, REQ-11, REQ-13 |
| `out-of-scope` | 1 | REQ-12 |
| **Total** | **17** | All S01 audit IDs covered |

Overall verdict: the repository has substantial deterministic implementation evidence for landing, repository shape, corpus/RAG fallback behavior, ensemble ranking, admin auth, and UI workflows, but several requirement areas remain only partially satisfied because live provider proof, operational metrics, non-functional measurements, or version/endpoint reconciliation are incomplete.

## Per-ID Verdict Matrix

| Audit ID | Requirements Area | Verdict | Confidence | Evidence Anchors | Caveats |
|---|---|---|---|---|---|
| REQ-01 | Versioning & Changelog | `pass` | High | `docs/REQUIREMENTS.md`, `.gsd/REQUIREMENTS.md`, `docs/M010-CLOSEOUT-EVIDENCE.md` | `prior_evidence_may_drift` for implementation status, but docs metadata/changelog exist. |
| REQ-02 | Landing Page - Gioi thieu du an | `partial` | Medium | `frontend/src/app/[locale]/page.tsx`, `frontend/src/components/landing/`, M010 frontend build evidence | FCP <= 1.5s and WCAG 2.2 AA need fresh performance/accessibility evidence; `prior_evidence_may_drift`. |
| REQ-03 | Boi canh & Muc tieu | `partial` | Medium | `data/tourism_documents.jsonl`, `data/eval_dataset.jsonl`, `agents/graph/agent_service.py`, `agents/guardrails/grounded_answer.py` | `credential_blocked`, `missing_operational_metrics`; cultural accuracy and displacement-reduction objectives need live/eval metrics. |
| REQ-04 | Cau truc Repository | `pass` | High | Current tree includes `docs/`, `frontend/`, `backend/`, `agents/`, `data/`, `scripts/`, `compose.yaml`, `README.md` | `version_drift` for illustrative tree names and moved route groups. |
| REQ-05 | Tech Stack & Phien ban chinh xac | `partial` | Medium | `frontend/package.json` shows Next 16.2.6, React 19.2.6, TypeScript 6.0.3; `compose.yaml`; backend/agent requirements | `version_drift`; declared package versions need S05 runtime verification. |
| REQ-06 | Kien truc he thong | `partial` | Medium | `backend/app/main.py`, `backend/app/routers/chat.py`, `backend/app/routers/admin.py`, `agents/graph/agent_service.py`, `compose.yaml` | `credential_blocked`, `prior_evidence_may_drift`; external-service paths need live proof. |
| REQ-07 | Google Places API (New) - Dac ta tich hop | `credential_blocked` | High for blocker, Medium for code | `agents/tools/places_service.py`, `agents/tools/routes_service.py`, `scripts/verify-google-places-live.py`, `docs/M005-PLACES-VERIFICATION-EVIDENCE.md` | `credential_blocked`; mocked contracts passed previously, live `RESULT=passed` needs valid Google credentials. |
| REQ-08 | Ensemble Methods - Ung dung ML Core | `partial` | Medium-High | `agents/ml/ensemble_reranker.py`, `agents/ml/feature_extractor.py`, M010/M006 evidence | Algorithm implementation is evidenced, but fairness impact needs `missing_operational_metrics` and fresh tests. |
| REQ-09A | Responsible AI - Reliability & Safety | `partial` | Medium | `agents/guardrails/`, `agents/guardrails/grounded_answer.py`, `backend/app/routers/chat.py`, `.gsd/REQUIREMENTS.md` R010/R015 | Semantic cache/RAGAS CI remain gaps; LLM flows are `credential_blocked`. |
| REQ-09B | Responsible AI - Fairness & Social Impact | `partial` | Medium | `agents/ml/ensemble_reranker.py`, `agents/ml/feature_extractor.py`, `scripts/monthly_fairness_audit.py`, admin fairness endpoint | `missing_operational_metrics`; operational fairness snapshots may be absent or insufficient. |
| REQ-09C | Responsible AI - Robustness & Security | `partial` | Medium-High | `backend/app/middleware/auth.py`, `backend/app/routers/admin.py`, `docs/AUDIT-AUTH-RATE-LIMITER.md`, M010 T05 admin JWT evidence | `endpoint_naming_drift`, `prior_evidence_may_drift`; auth appears wired now, but route naming/history must be reconciled. |
| REQ-09D | Responsible AI - Explainability & Transparency | `partial` | Medium | `agents/guardrails/grounded_answer.py`, `agents/graph/agent_service.py`, `backend/app/services/langfuse_service.py`, `frontend/src/components/reasoning/` | `credential_blocked` for live Langfuse traces; `missing_operational_metrics` for trace retention/query quality. |
| REQ-10 | Dac ta Module Frontend (Next.js 16) | `partial` | Medium | `frontend/package.json`, `frontend/src/app/[locale]/chat/page.tsx`, `frontend/src/app/[locale]/map/page.tsx`, `frontend/src/app/[locale]/admin/page.tsx`, M010 frontend evidence | Admin/chat polish gaps from `.gsd/REQUIREMENTS.md` R026/R028 need current S05 verification. |
| REQ-11 | Dac ta Module Agents (LangGraph) | `credential_blocked` | Medium | `agents/graph/agent_service.py`, `agents/tools/hybrid_retriever.py`, `agents/tools/embedding_service.py`, `agents/services/place_recommendation_service.py` | Core code exists, but OpenAI/Qdrant/Google live paths remain `credential_blocked`. |
| REQ-12 | Dac ta Module Backend (FastAPI) | `out-of-scope` | High | `docs/REQUIREMENTS.md` Section 12 is a module specification rather than a single atomic behavior; audited through REQ-06, REQ-09C, and REQ-13 | Not excluded from product scope, but out-of-scope as a standalone verdict because subcapabilities are separately covered. |
| REQ-13 | End-to-End Workflow | `credential_blocked` | Medium | `docs/M010-CLOSEOUT-EVIDENCE.md`, `scripts/verify-embedding-idempotency.py`, `scripts/verify-google-places-live.py`, `scripts/verify-session-durability.py` | End-to-end local UI proof exists historically, but full workflow live proof is `credential_blocked`. |
| REQ-14 | Phu luc: Glossary | `pass` | Medium | `docs/REQUIREMENTS.md`, `README.md`, terminology in docs/code | Documentation-only area; no runtime proof required. |

## Detailed Evidence Notes

### REQ-01 - Versioning & Changelog

`docs/REQUIREMENTS.md` contains a v3.0.0 metadata table, Semantic Versioning convention, status legend, and changelog entries for v1.0.0, v2.0.0, and v3.0.0. This satisfies the documentation requirement. Implementation status cited in the changelog can still drift from current code, so downstream reconciliation should not infer product pass/fail from the changelog alone.

### REQ-02 - Landing Page

The frontend manifest declares Next.js 16.2.6 and the S01 inventory maps landing sections to `frontend/src/app/[locale]/page.tsx` and `frontend/src/components/landing/`. M010 closeout records frontend type-check, lint, build, and prior browser checks. The verdict remains `partial` because this S02 task did not rerun frontend performance/accessibility gates and there is no fresh FCP <= 1.5s measurement.

### REQ-03 - Context & Objectives

The repository contains a normalized tourism corpus, evaluation dataset, grounded answer guardrails, and agent orchestration. Prior evidence validates corpus shape and no-evidence behavior. However, the broader objectives include cultural accuracy, economic-displacement mitigation, and transparent reasoning; those require live RAG/provider proof and operational metrics rather than only static code inspection.

### REQ-04 - Repository Structure

The expected top-level modules exist. Some paths in `docs/REQUIREMENTS.md` are illustrative or older than the current app structure, but the structural intent is met: docs, frontend, backend, agents, data, scripts, root compose file, and README are present.

### REQ-05 - Tech Stack & Versions

`frontend/package.json` confirms major frontend versions, including Next.js 16.2.6, React 19.2.6, Tailwind CSS 4.3.0, and TypeScript 6.0.3. Other versions must be confirmed from backend/agent manifests and the active Python environment during S05. Because `docs/REQUIREMENTS.md` includes exact version claims that may not match lock/runtime state, this area is `partial` with `version_drift`.

### REQ-06 - System Architecture

Core architecture files are present: FastAPI routers, agent service, hybrid retrieval, Qdrant tooling, and compose infrastructure. This supports the architecture diagram at a code-structure level. The paths that cross OpenAI, Qdrant, Google, and Langfuse cannot be fully proven without credentials and running services.

### REQ-07 - Google Places API (New)

`docs/M005-PLACES-VERIFICATION-EVIDENCE.md` records mocked backend tests and a live verifier that exits `RESULT=credential_blocked` when no Google key is available. The code includes Places and Routes services, and the verifier is designed not to leak secrets. The audit cannot mark this as pass until a valid key produces live normalized candidates and route matrix behavior.

### REQ-08 - Ensemble Methods

The ensemble and feature extraction files exist, and prior M006/M010 evidence records deterministic tests and UI score breakdowns. The implementation appears aligned with the 3-tree bagging plus 2-step boosting requirement. The verdict remains `partial` because fairness effect is not the same as algorithm existence; it needs durable fairness snapshots or operational audit metrics.

### REQ-09A - Reliability & Safety

Guardrail and grounded-answer modules provide deterministic safety surfaces, and `.gsd/REQUIREMENTS.md` records prior validation for citation/no-evidence behavior. Known gaps remain: semantic cache, RAGAS CI/CD, and live LLM-dependent behavior.

### REQ-09B - Fairness & Social Impact

The ensemble reranker and feature extractor support local-business preference and explainable score breakdowns. `scripts/monthly_fairness_audit.py` and the admin fairness surface indicate an audit path, but this report did not find evidence of sufficient durable operational snapshots. This is `partial` due to `missing_operational_metrics`.

### REQ-09C - Robustness & Security

Auth and rate-limiter documentation exists, and M010 records 39/39 admin JWT tests across embed, stats, eval, and traces. Current `backend/app/routers/admin.py` uses `Depends(get_current_user)` on admin endpoints. Endpoint naming has drifted historically: M010 evidence mentioned `/admin/eval`, the current source declares `POST /admin/eval/trigger`, and S01 explicitly warned that route names must be rechecked. S04 should reconcile stale requirement/status text against the current route table.

### REQ-09D - Explainability & Transparency

Grounded answer citations, reasoning components, reranker score breakdowns, and Langfuse service code provide explainability surfaces. Live Langfuse trace proof remains `credential_blocked`, and durable trace-retention/query-quality metrics remain unproven.

### REQ-10 - Frontend Module

The frontend has localized app routes for landing, chat, map, architecture, and admin surfaces, with Next.js 16 declared in `frontend/package.json`. Prior build and E2E evidence is strong, but `.gsd/REQUIREMENTS.md` still records admin dashboard and chat polish gaps. The frontend module is therefore `partial` pending fresh S05 verification and bounded S03 fixes or deferrals.

### REQ-11 - Agents Module

LangGraph orchestration, retrieval, places/routes tools, grounded answers, and ensemble reranking are represented in source. The module still depends on live OpenAI/Qdrant/Google paths for complete proof, so the highest honest verdict for the full module is `credential_blocked` rather than pass.

### REQ-12 - Backend Module

Section 12 is too broad to judge as a single behavior without double-counting. Backend capabilities are audited under architecture, security, and workflow IDs. Current source includes chat, auth, admin, and health routers; this row is `out-of-scope` only as a standalone verdict bucket, not as a claim that backend work is excluded from the product.

### REQ-13 - End-to-End Workflow

M010 evidence records local frontend/backend E2E checks for auth and chat, while M005/M009 evidence records credential-blocked provider verifiers. A complete user workflow includes live Places, embeddings/Qdrant, and tracing/evaluation paths, so full proof remains `credential_blocked` until valid services are available.

### REQ-14 - Glossary

The glossary section and terminology appear in `docs/REQUIREMENTS.md`. This is documentation consistency, not runtime behavior, so static documentation review is sufficient for a `pass` verdict.

## Credential and Live-Proof Limits

| Surface | Local Evidence | Blocked Proof | Unblock Condition |
|---|---|---|---|
| Google Places/Routes | Mocked service tests and `scripts/verify-google-places-live.py` credential-blocked path | Live `RESULT=passed` from Places API and Routes matrix | Valid Google API key(s), enabled APIs, network access |
| OpenAI embeddings/RAGAS | Embedding service code, hybrid retriever tests, credential-blocked verifier behavior | Live `/admin/embed`, Qdrant point counts, RAGAS metrics | Valid `OPENAI_API_KEY`, running Qdrant/backend |
| Qdrant | Qdrant service code and prior local tests | Live vector collection/upsert/search proof | Running Qdrant with expected collection/vector schema |
| Langfuse | `backend/app/services/langfuse_service.py`, admin traces status surface | Live trace ingestion/query proof | Valid Langfuse host/public/secret keys and reachable service |

Credential-blocked outcomes are honest audit states, not failures. They must not be converted to pass using mocked tests or prior prose.

## Endpoint and Version Drift

- `endpoint_naming_drift`: S01 warned that requirements/prior evidence may say `POST /admin/eval/trigger` or `POST /admin/eval`. Current source inspection shows `backend/app/routers/admin.py` declares `POST /admin/eval/trigger`, `GET /admin/eval/results`, `GET /admin/traces`, `GET /admin/fairness`, and `GET /admin/stats`. M010 closeout text cited `/admin/eval` in places, so downstream agents should treat older endpoint names as stale until tests confirm them.
- `version_drift`: `docs/REQUIREMENTS.md` exact versions are not automatically true for the active runtime. `frontend/package.json` currently declares Next.js 16.2.6, React 19.2.6, Tailwind CSS 4.3.0, and TypeScript 6.0.3. Backend and agent versions require manifest/runtime checks in S05.
- `prior_evidence_may_drift`: M002-M010 evidence remains useful but should be superseded by current source and fresh command output when conflicts appear.

## S03 Candidates

| Candidate | Type | Bounded Action or Deferral | Related IDs |
|---|---|---|---|
| Reconcile admin endpoint naming | Bounded fix | Align docs/tests/frontend API client with current `/admin/eval/trigger` or intentionally add compatibility only if required. | REQ-09C, REQ-12 |
| Add/administer route table verifier | Bounded fix | Add a static or pytest check that asserts expected admin paths and auth dependencies. | REQ-09C, REQ-12 |
| Record frontend non-functional proof | Bounded verification | Run or add lightweight checks for landing responsive/accessibility/FCP claims; defer exact lab performance if environment is unsuitable. | REQ-02, REQ-10 |
| Strengthen fairness audit evidence | Bounded fix or deferral | Ensure `scripts/monthly_fairness_audit.py` produces durable non-secret snapshots, or explicitly defer operational metrics to follow-up. | REQ-08, REQ-09B |
| Clarify backend module verdict granularity | Documentation fix | In S04, avoid one broad backend status if subcapabilities differ; reconcile by concrete endpoints/tests. | REQ-12 |
| Preserve credential-blocked provider gates | Explicit deferral | Keep Google/OpenAI/Qdrant/Langfuse live proof as credential-blocked unless credentials are provided. | REQ-07, REQ-11, REQ-13 |
| Update version contract | Bounded docs/status fix | Compare `docs/REQUIREMENTS.md` tech-stack versions to manifests and mark drift explicitly. | REQ-05 |
| RAGAS/semantic cache scope decision | Explicit deferral | Treat RAGAS CI/CD and Redis semantic cache as major follow-up work unless already implemented by current code. | REQ-09A |

## S03 Remediation Outcomes

S03 keeps the audit bounded: small source/test/documentation gaps are fixed or guarded by static diagnostics, while live-provider, production-metrics, and major subsystem gaps remain explicit deferrals for S04/S05 or later milestones.

| Candidate | Outcome | Status | Evidence | Bounded Caveat |
|---|---|---|---|---|
| Reconcile admin endpoint naming | Current source and tests use `POST /admin/eval/trigger`; stale `/admin/eval` wording remains documented only as historical drift. | fixed | `backend/app/routers/admin.py`, `backend/tests/test_admin_eval_endpoint.py`, `frontend/src/lib/admin-api.ts`, `frontend/src/app/api/admin/route.ts`, `scripts/verify-m011-s03-bounded-fixes.mjs` | Do not add `POST /admin/eval` compatibility without a separate product decision. |
| Add/administer route table verifier | The S03 static verifier asserts `/admin` route names and `Depends(get_current_user)` coverage for embed, eval, traces, fairness, and stats. | fixed | `scripts/verify-m011-s03-bounded-fixes.mjs`, `backend/tests/test_admin_embed_auth.py`, `backend/tests/test_admin_eval_endpoint.py`, `backend/tests/test_admin_stats_endpoint.py`, `backend/tests/test_admin_traces_endpoint.py` | Static route/auth proof does not replace runtime API or browser verification. |
| Record frontend non-functional proof | Exact FCP/accessibility lab proof remains outside this bounded slice; S05 should run fresh frontend build/browser/performance checks. | deferred | `frontend/package.json`, `frontend/tests/s07-auth-e2e.test.mjs`, `docs/M010-CLOSEOUT-EVIDENCE.md` | `prior_evidence_may_drift`; no new FCP <= 1.5s claim is made here. |
| Strengthen fairness audit evidence | Local fairness proof is bounded to JSONL aggregation, admin fairness tests, and script `PASS`/`FAIL`/`NO_DATA` output; production operational metrics remain deferred. | fixed+deferred | `scripts/monthly_fairness_audit.py`, `backend/tests/test_fairness_audit.py`, `backend/tests/test_admin_traces_endpoint.py`, `scripts/verify-m011-s03-bounded-fixes.mjs` | `NO_DATA` is an honest local result when no snapshots exist; durable monthly history is still `missing_operational_metrics`. |
| Clarify backend module verdict granularity | Backend status remains split across concrete endpoints and requirement IDs instead of a single broad pass/fail bucket. | fixed | REQ-06, REQ-09C, REQ-12 notes in this report | S04 owns `.gsd/REQUIREMENTS.md` status reconciliation. |
| Preserve credential-blocked provider gates | Google, OpenAI, Qdrant, Langfuse, and full live workflow proof remain `credential_blocked` until real credentials/services are available. | deferred | `scripts/verify-google-places-live.py`, `scripts/verify-embedding-idempotency.py`, `backend/requirements.txt`, `agents/requirements.txt` | Mocked or static checks must not be reported as live provider success. |
| Update version contract | Manifest evidence is recorded for frontend/backend/agent dependency drift; runtime/version reconciliation remains for S05. | fixed+deferred | `frontend/package.json`, `backend/requirements.txt`, `agents/requirements.txt`, `scripts/verify-m011-s03-bounded-fixes.mjs` | `version_drift`; manifests are static evidence, not installed runtime proof. |
| RAGAS/semantic cache scope decision | RAGAS CI/CD and production semantic cache proof are explicitly deferred as major follow-up work. | deferred | REQ-09A notes in this report, `backend/requirements.txt`, `agents/requirements.txt` | No Redis semantic-cache production behavior or RAGAS CI/CD is implemented by this S03 task. |

## Verification Appendix

This S02 task creates an audit inspection surface. Verification for this report is intentionally lightweight and static; S05 owns strongest practical local verification.

| Check | Expected Result | Notes |
|---|---|---|
| `node --test scripts/verify-m011-s01-inventory.mjs scripts/verify-m011-s02-audit.mjs` | Exit 0; 7/7 tests passed on 2026-05-22 | Static traceability proof only: confirms S01 inventory coverage and S02 report shape/caveat/verdict preservation; does not prove live OpenAI, Google, Qdrant, Postgres/Redis, or Langfuse behavior. |
| `test -s docs/M011-REQUIREMENTS-AUDIT.md` | Covered by node:test report existence assertion | Confirms durable report exists and is non-empty. |
| Coverage review | Covered by node:test canonical ID assertions | REQ-01 through REQ-08, REQ-09A through REQ-09D, REQ-10 through REQ-14 included. |
| Caveat preservation review | Covered by node:test caveat assertions | `credential_blocked`, `endpoint_naming_drift`, `version_drift`, `missing_operational_metrics`, `prior_evidence_may_drift`. |
| S03 candidate review | Covered by node:test section assertions | Bounded fixes and explicit deferrals listed without implementing them. |

### S03 Targeted Remediation Verification

| Check | Exit Code | Result | Notes |
|---|---:|---|---|
| `node --test scripts/verify-m011-s01-inventory.mjs scripts/verify-m011-s02-audit.mjs scripts/verify-m011-s03-bounded-fixes.mjs && pytest -q backend/tests/test_admin_eval_endpoint.py backend/tests/test_admin_stats_endpoint.py backend/tests/test_admin_traces_endpoint.py backend/tests/test_admin_embed_auth.py backend/tests/test_fairness_audit.py && python3 scripts/monthly_fairness_audit.py --days 30` | 0 | Static checks passed; targeted backend pytest passed; monthly fairness audit reported `PASS`. | 18/18 node:test assertions passed, 48 backend tests passed with 13 warnings, and local fairness aggregation found 33 snapshots, 33 places, 100.0% local business share, and 0/33 snapshot violations. This is local audit evidence, not production operational history. |
| Initial same-command attempt before `backend/pytest.ini` path fix | 4 | Static node checks passed; repo-root pytest import failed before monthly fairness ran. | Failure localized to `ModuleNotFoundError: No module named 'agents'` from `backend/tests/conftest.py`; `backend/pytest.ini` now includes `..` so repo-root imports are available under the original verification command. |
| `pytest -q backend/tests/test_admin_eval_endpoint.py backend/tests/test_admin_stats_endpoint.py backend/tests/test_admin_traces_endpoint.py backend/tests/test_admin_embed_auth.py backend/tests/test_fairness_audit.py` | 0 | 48 passed, 13 warnings. | Targeted backend-only rerun confirmed the import-path fix before the aggregate gate. |

### S04 Reconciliation Outcome

S04 records the requirement-status reconciliation contract that S05 can cite without weakening S01-S03 audit boundaries. The canonical reconciliation matrix is `docs/M011-S04-REQUIREMENT-RECONCILIATION.md`, and the source-tree diagnostic is `scripts/verify-m011-s04-reconciliation.mjs`.

| Requirement Set | Reconciliation Action | Evidence | Caveat Boundary |
|---|---|---|---|
| R013, R015, R029, R031 | Validate only where deterministic corpus, grounded-answer, audit-process, or bounded S03 remediation evidence directly supports the requirement. | `docs/M011-S04-REQUIREMENT-RECONCILIATION.md`; S01/S02/S03/S04 verifier scripts; backend corpus/admin/fairness tests cited by S03. | Validation is scoped to the evidenced behavior and must not expand into live RAG quality, provider success, or production metrics. |
| R007, R008, R010, R011, R026, R028, R033 | Keep active when implementation is partial, credentialed proof is blocked, frontend polish/nonfunctional checks are pending, or S05 owns strongest-practical verification. | `.gsd/REQUIREMENTS.md`; `docs/M011-REQUIREMENTS-AUDIT.md`; `docs/M011-S04-REQUIREMENT-RECONCILIATION.md`; current admin/frontend/backend surfaces. | Keep `credential_blocked`, `deferred_major_scope`, `missing_operational_metrics`, `frontend_nonfunctional_pending`, and `endpoint_naming_drift` language intact. |
| R032, R034 | Validate after reconciliation evidence only when the matrix, S04 verifier, and official `.gsd/REQUIREMENTS.md` reconciliation path preserve explicit deferrals. | `docs/M011-S04-REQUIREMENT-RECONCILIATION.md`; `scripts/verify-m011-s04-reconciliation.mjs`; this audit appendix. | Do not silently close RAGAS CI/CD, Redis semantic cache, live provider proof, production fairness history, frontend nonfunctional proof, or S05 verification scope. |

The `.gsd/REQUIREMENTS.md` update boundary remains DB-backed/official-tool owned. S04 did not manually rewrite the canonical requirements file; if an official update operation is unavailable or blocked, the durable source evidence is this audit section plus `docs/M011-S04-REQUIREMENT-RECONCILIATION.md`, and S05 must treat unsupported status changes as drift.

Blocked or deferred requirement-update operations:

- Live OpenAI, Google, Qdrant, Langfuse, RAGAS, semantic cache, production fairness history, and frontend performance/accessibility proof were not run or claimed in S04.
- Credential-dependent checks require valid credentials, running services, and network access before any `credential_blocked` row can become a live pass.
- The exact combined static gate for S05 reuse is `node --test scripts/verify-m011-s01-inventory.mjs scripts/verify-m011-s02-audit.mjs scripts/verify-m011-s03-bounded-fixes.mjs scripts/verify-m011-s04-reconciliation.mjs`.

## Confidence Notes

- High confidence: documentation structure, repository structure, credential-blocked classification, and current admin route names observed directly from source.
- Medium confidence: frontend, ensemble, guardrail, and admin auth status because this task relies on current source plus prior evidence rather than fresh full test runs.
- Lower confidence: operational fairness, live RAG/Places/Langfuse quality, FCP/accessibility, and exact runtime dependency versions until S05 executes the verification suite.
