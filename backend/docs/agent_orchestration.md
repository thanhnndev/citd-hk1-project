# Agent Orchestration Operations

This service routes both `POST /chat` and `GET /chat/stream` through the shared `AgentService` created during FastAPI startup. The service owns retrieval, grounded answer generation, LangGraph execution, per-session memory, and streaming response assembly so the synchronous and SSE paths use the same behavior.

## Runtime Shape

- FastAPI startup creates one `app.state.agent_service` after retrievers and answer services are initialized.
- `backend/app/routers/chat.py` keeps the public response contracts for `POST /chat` and `GET /chat/stream`, but delegates agent work to the shared service.
- Each request carries a `session_id`; the LangGraph thread id is derived from that value so follow-up questions can use the same conversation context.
- The graph has retrieval, answer, fallback, and completion phases. It returns grounded citations when evidence exists and an honest no-evidence answer when retrieval cannot support the question.
- Streaming responses emit answer chunks, citation metadata, and a terminal completion marker while preserving the existing frontend SSE parser contract.

## Checkpoint Configuration

Production deployments should enable PostgreSQL-backed LangGraph checkpointing with pooled database connections. Use placeholder secret names in manifests and inject the real values from the deployment secret manager.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection string used by the checkpoint backend. |
| `LANGGRAPH_CHECKPOINT_TABLE` | Optional checkpoint table name when the deployment needs a non-default table. |
| `LANGGRAPH_CHECKPOINT_POOL_SIZE` | Optional pool size for concurrent session checkpoint writes. |

When PostgreSQL checkpoint setup is unavailable, local and test runs fall back to in-memory checkpointing. This keeps unit tests and local browser flows deterministic, but memory checkpoints are process-local and must not be treated as durable production state.

## Operational Logging

Structured logs intentionally include correlation and phase metadata, not secrets or full conversation text. Useful fields include:

- `session_id` and request correlation context for tying backend logs to browser failures.
- Agent invocation start and completion events.
- Graph phase names for retrieval, answer generation, fallback, and stream completion.
- Checkpoint mode, so operators can confirm `postgres` versus local memory fallback.
- Retrieval counts and fallback reason, so no-evidence answers can be distinguished from infrastructure failures.
- Stream lifecycle events for SSE start, chunk/citation emission, completion, and error fallback.

## Troubleshooting

- If follow-up questions ignore context, confirm the same `session_id` is present in frontend requests and backend logs.
- If every response is no-evidence, inspect retrieval count logs and Qdrant/hybrid retriever startup logs before changing prompts.
- If production latency rises with many concurrent sessions, check PostgreSQL checkpoint pool saturation and database wait time metrics; increase pool capacity only after confirming database headroom.
- If SSE fails in the browser, compare Playwright assertions with backend stream lifecycle logs and the fallback `POST /chat` request.
- If local tests do not have PostgreSQL checkpoint packages or a database URL, expect memory checkpoint mode rather than a hard startup failure.

## Closeout Gates

Run these commands from the repository root when validating the S05 assembly:

```bash
cd backend && python -m pytest tests/ -q --tb=short
cd frontend && bun run type-check
cd frontend && bun run lint
cd frontend && bun run build
cd frontend && node tests/s05-chat-e2e.test.mjs
```

For automation that invokes the browser gate from the repository root, `node tests/s05-chat-e2e.test.mjs` delegates to the same frontend test file.
