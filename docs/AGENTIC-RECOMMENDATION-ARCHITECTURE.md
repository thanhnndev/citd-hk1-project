# Agentic Recommendation Architecture

This document describes the production architecture for the Ham Ninh AI Guide chat and recommendation system. The goal is to behave like an end-user travel assistant, not a demo that dumps provider search results.

## Product Principle

The assistant must return travel decisions, not raw data.

A provider such as Google Places or Goong can return candidates that match text, but matching text is not the same as being a useful recommendation. The agent stack therefore separates:

1. Semantic tool choice by the LLM.
2. Grounded data retrieval from tools.
3. Product-level suitability evaluation.
4. Curated end-user response composition.
5. UI presentation with progressive disclosure.

## High-Level Flow

```text
User message
  -> AgentService LangGraph-style loop
  -> LLM decides direct answer or tool call
  -> search_knowledge or search_places tool executes
  -> backend service grounds and curates results
  -> assistant response + citations/places/suggestions
  -> frontend renders decision-ready answer
```

The conditional graph edge does not classify user intent by keyword. It only checks whether the LLM emitted tool calls. Domain decisions stay inside the LLM/tool-calling loop.

## AgentService Responsibilities

`agents/graph/agent_service.py` owns orchestration:

- Builds the LangGraph-style `llm_call -> tool_node -> llm_call` loop.
- Lets the LLM decide whether to call `search_knowledge` or `search_places`.
- Keeps deterministic preflight limited to safe conversational cases: empty input, greetings, thanks, and capability/help.
- Does not hard-route domain queries by keyword.
- Persists conversation history and structured follow-up context.
- Emits streaming status events for user-visible progress.

## Tool Contracts

### `search_knowledge`

Used when the user wants to understand Ham Ninh:

- culture and local life
- history
- fishing village context
- food background
- factual travel explanations

Knowledge answers must be grounded in retrieved chunks and citations. If evidence is weak, the answer should say so instead of inventing facts.

### `search_places`

Used when the user wants concrete venues, routes, nearby options, or recommendations:

- restaurants and seafood places
- cafes
- homestays and hotels
- attractions
- itinerary stops
- directions or route-oriented requests

The places tool returns grounded `PlaceResult` objects only from provider candidates. It must not invent place IDs.

## Recommendation Pipeline

`agents/services/place_recommendation_service.py` is the production recommendation seam.

```text
Places query
  -> PlaceSearchRequest
  -> provider text_search
  -> optional route enrichment
  -> preference filters
  -> RecommendationFrame
  -> CandidateSuitability evaluation
  -> ensemble reranking
  -> fairness balancing
  -> user-facing explanation
  -> ChatResponse
```

### RecommendationFrame

`RecommendationFrame` is a product-level interpretation of what a useful recommendation must optimize for. It is not a route classifier. The LLM has already chosen the places tool; the frame describes the shape of the recommendation.

Current frame fields include:

- `goal`: visit, itinerary, food, stay
- `audience`: general, family, accessibility
- `desired_roles`: acceptable roles for candidates
- `disallowed_roles`: roles that should not be primary recommendations
- `constraints`: product constraints such as low friction or accessibility

### CandidateSuitability

`CandidateSuitability` evaluates each normalized provider candidate against the frame:

- `role`: visit, eat, stay, shop, service, unknown
- `score`: product suitability score
- `disqualified`: whether the candidate should be excluded from primary results
- `primary_reason_vi` / `primary_reason_en`: user-facing explanation
- `caveats`: bounded warnings when relevant

This fixes the root issue where provider matches were treated as recommendations. For example, a baby shop can match a family-related query, but its role is `shop`, not `visit`, so it should not appear as a primary itinerary recommendation.

## Response Composition

The assistant response should be curated:

- Mention the top few options, not every provider candidate.
- Explain why the options fit the user's travel goal.
- Keep diagnostics in `reasoning_log` and structured fields, not in user-facing copy.
- Return exact places in `places` for cards/maps.
- Use suggestions to continue the task.

Do not expose provider/debug strings such as:

- `Provider Rating Available`
- `Type Label`
- `accessibility score 1.00`
- raw payment or parking metadata as primary rationale
- raw score axes in the default user view

## Frontend Presentation

The frontend must be an end-user interface, not an observability console.

Current chat UI principles:

- Welcome screen uses intent launcher cards instead of plain instructional text.
- Place cards show friendly category, rating, address, practical reason, and map action.
- Only the first 3 place cards are shown by default.
- Extra places are behind progressive disclosure.
- Streaming status is shown while processing, but internal timeline is hidden after completion.
- Technical score/source details are hidden behind explicit details controls.

## Evaluation Strategy

Following product-eval best practice, tests should verify behavior in the application context, not just model/tool mechanics.

Important dimensions:

- Tool-use correctness: LLM chooses the right tool path.
- Suitability correctness: candidates are useful for the user's goal.
- Disqualification correctness: service/shop/admin candidates are not primary trip recommendations.
- Grounding: knowledge answers cite sources; place results come from provider candidates.
- Presentation safety: no raw provider/debug strings leak to end users.
- Output structure: responses carry citations/places/suggestions in the expected schema.
- Task completion: the user receives a decision-ready answer.

Product evals should start small with real failure modes and expand from production traces.

## Key Files

| Area | File |
|---|---|
| Agent orchestration | `agents/graph/agent_service.py` |
| Tool prompt and schemas | `agents/graph/state.py` |
| Safe fallback and suggestions | `agents/graph/routing.py` |
| Follow-up context | `agents/graph/followup.py` |
| Places recommendation seam | `agents/services/place_recommendation_service.py` |
| Places models | `backend/app/models/places.py` |
| Chat response models | `backend/app/models/response.py` |
| Chat UI | `frontend/src/components/chat/chat-interface.tsx` |
| Assistant message rendering | `frontend/src/components/chat/message-bubble.tsx` |
| Place cards | `frontend/src/components/chat/place-card.tsx` |

## Non-Goals

- Do not add keyword-based domain routing before the LLM.
- Do not patch individual user phrases with one-off filters.
- Do not use RAG documents to fake place results when the places provider is unavailable.
- Do not expose internal ranking/provider diagnostics as default user copy.
