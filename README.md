# Ham Ninh AI Guide

AI travel assistant for Ham Ninh fishing village, Phu Quoc.

The product combines grounded cultural answers, place search, deterministic fairness re-ranking, maps, and explicit agent run-state so users can inspect progress and evidence instead of reading a generic chatbot transcript.

## Core Product Principles

- The UI is an execution console: conversation, run state, evidence, artifacts, and recovery controls are separate concerns.
- Responsible AI is enforced through retrieval grounding, guardrails, fairness audit metadata, score explanations, and evals. It is implemented as behavior, receipts, and quality gates, not as decorative marketing UI.
- Place providers return candidates, not final recommendations. The backend filters and ranks candidates before presentation.
- Recommendation scoring is deterministic and auditable. The project does not use hidden or trained ranking models.

## Architecture

| Area | Runtime role | Key files |
|---|---|---|
| Agent state and tools | Typed state, tool contracts, prompt, timeouts | `agents/graph/state.py` |
| Graph execution | LangGraph-style run, streaming, checkpointing | `agents/graph/ham_ninh_graph.py`, `agents/graph/streaming.py` |
| Chat API | REST/SSE chat endpoints and resume/feedback routes | `backend/app/routers/chat.py` |
| Retrieval | Hybrid/local corpus retrieval for cultural answers | `agents/tools/hybrid_retriever.py`, `agents/tools/retriever.py` |
| Places | Provider search, normalization, routes, cache fallback | `agents/tools/places_service.py`, `agents/tools/routes_service.py` |
| Recommendations | Suitability filtering, fairness re-ranking, explanation | `agents/services/place_recommendation_service.py`, `agents/ranking/fairness_reranker.py` |
| Frontend | Next.js App Router chat, map, architecture, auth | `frontend/src/app`, `frontend/src/components` |

## Agent Run-State Contract

The frontend consumes semantic status events, not internal node names:

- `planning`
- `gathering:knowledge`
- `gathering:places`
- `executing`
- `waiting_for_user_input`
- `waiting_for_approval`
- `retrying`
- `verifying`
- `completed`
- `failed-recoverable`
- `failed-terminal`

The UI should translate these into useful progress messages and receipts. Do not expose internal policy axes as progress steps.

## SSE Streaming Contract

`GET /chat/stream` is event streaming. Raw SSE data without a marker is reserved for real LLM token chunks emitted through LangGraph custom `token` events. Completed node responses from deterministic/tool paths are sent as `[MESSAGE] ...`, followed by structured markers such as `[PLACES]`, `[CITATIONS]`, `[SUGGESTIONS]`, `[REASONING]`, and `[DONE]`.

Do not split completed `response_text` into fake token chunks. If a path cannot stream from the underlying model/provider, emit semantic status events and one `[MESSAGE]` receipt.

## Recommendation Pipeline

1. Provider tooling returns normalized place candidates.
2. Preference and product-suitability filters remove candidates that do not fit the travel task.
3. The deterministic fairness re-ranker scores relevance, proximity, quality, geo-locality, popularity damping, and accessibility signals.
4. Fairness balancing and audit metadata record local representation, missing metadata, provider status, and fallback warnings.
5. The frontend shows place cards, score explanations, provider evidence, and map links.

## Development

```bash
cp .env.example .env
docker compose up
```

Useful checks:

```bash
cd frontend
npm run type-check
npm run build
node --test tests/s01-landing-contract.test.mjs tests/s05-messenger-chat-contract.test.mjs tests/s13-chat-redesign-contract.test.mjs
```

```bash
PYTHONPATH=backend:. .venv/bin/pytest -q agents/graph/test_streaming.py
```

## Documentation

- [Requirements](docs/REQUIREMENTS.md)
- [Agent orchestration](backend/docs/agent_orchestration.md)
