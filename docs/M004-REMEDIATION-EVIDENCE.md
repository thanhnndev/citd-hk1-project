# M004 Remediation Evidence

This artifact consolidates the S06/S07 validation-remediation path for retrying M004 validation. It records the local evidence produced through S07, the exact commands used, current blocked reasons, and the commands needed to rerun validation in a credentialed environment.

## Validation Remediation Items

| Item | Status | Evidence | Retry Guidance |
|---|---|---|---|
| R007 / external dependency readiness and skipped-live-test reasons | S07 blocked by missing OpenAI credential; backend and Qdrant readiness captured | 2026-05-18T15:04:46Z: `OPENAI_API_KEY` status was `missing` (secret not printed). Backend health at `http://localhost:48721` returned 200 `{"status":"ok"}`. Qdrant at `http://localhost:46333` returned collection `tourism_chunks` with 0 points and legacy unnamed 1536-dimensional vector config; named `dense` vector was not present because live ingestion did not run. Root semantic gate `pytest -q tests/test_embedding_search.py --tb=short -rs` exited 0 with 15 passed and 6 credential skips. | Export a real `OPENAI_API_KEY`, keep backend at `http://localhost:48721` or set `BACKEND_URL`, keep Qdrant at `http://localhost:46333` or set `QDRANT_URL`, then rerun the S07 commands in this artifact. |
| 10+ hybrid query evaluation | Passed with deterministic local evidence | `cd backend && pytest -q tests/test_hybrid_search.py::test_fixture_hybrid_vs_keyword_recall_10_queries -s` exited 0 and emitted 10 fixed tourism query rows where hybrid recall was greater than or equal to keyword-only recall. `cd backend && pytest -q tests/test_hybrid_search.py -s` exited 0 with 16 passed and 5 skipped. | Rerun the deterministic command for local proof. In a credentialed environment, rerun the full hybrid test file to include live integration coverage. |
| Embedding/Qdrant index proof | S07 credential-blocked locally; hardened verifier captured dependency state | `python3 scripts/verify-embedding-idempotency.py` exited 0 with `RESULT=credential_blocked`. Config: backend `http://localhost:48721`, Qdrant `http://localhost:46333`, collection `tourism_chunks`, expected points 321, expected vector dimension 1536, OpenAI key status `missing`. Before-run collection state: 0 points, `vector_config={"distance":"Cosine","size":1536}`, named dense vector absent. No embed run summaries were produced because the verifier stopped before calling `/admin/embed` without a real key. | `export OPENAI_API_KEY=<valid key>`; ensure Qdrant and backend are running; run `python3 scripts/verify-embedding-idempotency.py`. Passing live state must report two successful `/admin/embed` runs, final 321 points, and 1536-dimensional dense vectors. |
| Embed idempotency | S07 credential-blocked locally; backend/Qdrant reachable | The verifier is designed to POST `/admin/embed` twice and compare Qdrant state after both runs, but local execution could not run the live embed path because `OPENAI_API_KEY` was missing. Backend and Qdrant were reachable, so the remaining blocker is a valid OpenAI credential plus any resulting live provider/runtime failures. | With a valid key and running backend/Qdrant, run `python3 scripts/verify-embedding-idempotency.py`; accept only `RESULT=idempotent_verified` or equivalent successful two-run evidence with point count unchanged at 321 after both runs. |
| Session durability or explicit re-scope | Explicitly re-scoped locally; Postgres durability rerunnable | `python3 scripts/verify-session-durability.py` exited 0 with `RESULT=rescope_required`, `DATABASE_URL_STATUS=missing`, `CHECKPOINT_MODE=memory`, `CHECKPOINTER_CLASS=InMemoryAgentCheckpointer`, `MEMORY_BEFORE_RESTART_LEN=2`, and `MEMORY_AFTER_RESTART_LEN=0`. Memory checkpoint mode is same-process only and is not restart durable. `cd backend && pytest -q tests/test_agent_service.py --tb=short` exited 0 with 7 passed. | For durable sessions, provide a working Postgres `DATABASE_URL` and run `python3 scripts/verify-session-durability.py`; accept only `RESULT=durable_verified` for restart durability, otherwise treat memory mode as intentionally re-scoped. |

## Command Evidence

| # | Command | Exit Code | Verdict | Source |
|---|---|---:|---|---|
| 1 | `cd backend && pytest -q tests/test_hybrid_search.py::test_fixture_hybrid_vs_keyword_recall_10_queries -s` | 0 | Passed; emitted 10 query rows with hybrid >= keyword | S06/T02 |
| 2 | `cd backend && pytest -q tests/test_hybrid_search.py -s` | 0 | Passed; 16 passed, 5 skipped for unavailable live credentials | S06/T02 |
| 3 | `python3 scripts/verify-embedding-idempotency.py` | 0 | Passed as diagnostic; reported `RESULT=credential_blocked` with Qdrant/backend/OpenAI readiness details | S06/T03 |
| 4 | `cd backend && pytest -q tests/test_embedding_search.py::TestEmbeddingIntegration::test_embed_query_real_vector_shape tests/test_embedding_search.py::TestEmbeddingIndex --tb=short -rs` | 0 | Passed as credential-blocked skip evidence | S06/T03 |
| 5 | `python3 -m py_compile scripts/verify-embedding-idempotency.py` | 0 | Passed syntax check | S06/T03 |
| 6 | `cd backend && pytest -q tests/test_agent_service.py --tb=short` | 0 | Passed; 7 agent service tests including memory restart-loss and Postgres fallback coverage | S06/T04 |
| 7 | `python3 scripts/verify-session-durability.py` | 0 | Passed as diagnostic; reported `RESULT=rescope_required` in memory mode | S06/T04 |
| 8 | `python3 -m py_compile scripts/verify-session-durability.py` | 0 | Passed syntax check | S06/T04 |
| 9 | `python3 scripts/verify-embedding-idempotency.py` | 0 | S07 blocked diagnostic; `RESULT=credential_blocked`, OpenAI key status `missing`, backend `http://localhost:48721` health 200, Qdrant `http://localhost:46333` collection reachable with 0 points and 1536-dimensional vector config | S07/T04 |
| 10 | `pytest -q tests/test_embedding_search.py --tb=short -rs` | 0 | S07 semantic gate passed locally with 15 passed and 6 credential skips from missing/fake `OPENAI_API_KEY` | S07/T04 |

## Validation Retry Procedure

1. Start Qdrant and the backend API with the same settings used for production-like validation.
2. Export real credentials: `export OPENAI_API_KEY=<valid key>` and, for durable sessions, `export DATABASE_URL=<postgres dsn>`.
3. Run `cd backend && pytest -q tests/test_hybrid_search.py -s` and confirm the 10-query hybrid evidence remains passing and live tests no longer skip when dependencies are available.
4. Run `pytest -q tests/test_embedding_search.py --tb=short -rs` from the repository root or `cd backend && pytest -q tests/test_embedding_search.py --tb=short -rs` and confirm credentialed semantic tests pass without skip.
5. Run `python3 scripts/verify-embedding-idempotency.py` and confirm `/admin/embed` can run twice, Qdrant reports 321 points, and vectors are 1536-dimensional after both runs.
6. Run `python3 scripts/verify-session-durability.py` and confirm either `RESULT=durable_verified` with Postgres checkpointing or retain the explicit memory-mode re-scope if restart durability is outside the accepted milestone scope.

## Current Validation Position

M004 can be retried against this artifact with concrete evidence for all five remediation items. Local validation should treat the hybrid recall proof, agent-service regression tests, and non-credentialed embedding search tests as passing, while live embedding/idempotency still requires a real `OPENAI_API_KEY` before it can be claimed as a live pass. Postgres restart durability requires `DATABASE_URL` unless memory-mode re-scope remains accepted.
