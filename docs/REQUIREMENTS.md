# Current Requirements

This document is intentionally short and current. Obsolete UI and ranking-model requirements were removed because they conflict with the production UX and runtime design.

## Product Scope

Ham Ninh AI Guide helps visitors:

- ask cultural, historical, food, and travel questions about Ham Ninh;
- discover relevant places and routes;
- inspect citations, provider evidence, score explanations, and recommendation receipts;
- recover from missing data, denied location access, provider failure, and retryable agent errors.

## UI/UX Requirements

- The chat page must separate user transcript from agent execution state.
- Streaming progress must use semantic run states such as `planning`, `gathering:knowledge`, `gathering:places`, `waiting_for_user_input`, `verifying`, and retry/failure states.
- Streaming must not fake token output. Raw token chunks are allowed only when the underlying LLM stream emits tokens; completed deterministic/tool responses must use a full-message event.
- Browser geolocation may be requested only when the task depends on the user's current position (`near me`, `around here`, or a route from the current position). Proximity to a named landmark or feature such as a beach does not justify a location permission request.
- A paused run must resume on the same LangGraph `thread_id` with `Command(resume=...)`; confirmation text must not be submitted as an unrelated new chat turn.
- The UI must not present Responsible AI policy axes as public cards, steppers, or checklist content.
- Every recommendation or grounded answer should expose user-relevant evidence: citations, place provider status, score details, route/accessibility context, and fallback notes.
- Failure states must explain what failed, whether retry is safe, and what the user can do next.

## Agent State Requirements

Minimum persisted or replayable state:

- goal/message and language;
- conversation history and checkpoint thread;
- run status and current step;
- tool calls and structured tool receipts;
- citations, places, suggestions, reasoning summary;
- pending user input or approval state;

Turn-scoped outputs such as response text, places, citations, suggestions, routing decisions, and location requirements must be reset when a new user turn starts. Checkpoint persistence must preserve conversation memory without leaking prior-turn execution output into the next run.
- retry count and recoverable/terminal error code.

## Retrieval Requirements

- Cultural answers must be grounded in retrieved corpus data.
- Empty or weak evidence must produce a transparent fallback instead of invented facts.
- Citations are source evidence, not decorative labels.

## Place Recommendation Requirements

- Provider results are candidates only.
- Candidate suitability filtering must run before ranking and presentation.
- Ranking must be deterministic and auditable. Do not introduce hidden or trained ranking models for this project.
- Score explanations should use practical signals: relevance, proximity, quality, geo-locality, popularity damping, accessibility, weights, gate status, final score, and rank.
- Accessibility support claims require provider-verified evidence for the specific need, such as `wheelchairAccessibleEntrance=true` for wheelchair entrance access. Partial, negative, or unknown accessibility metadata must not be converted into “accessible” labels.
- Accessibility filtering is explicit opt-in from the current request or UI control; it must not silently constrain every place search.
- Explicit place categories such as cafe must be sent to the provider as typed constraints and enforced again after normalization. A restaurant is not a valid cafe result merely because both are food venues.
- Comparative follow-ups must operate on the previous grounded candidate set and preserve its query constraints. They must not trigger an unrelated fresh search.
- Family/children place questions must use grounded place data. The assistant must not invent beaches, parks, activities, safety, or child suitability without provider or retrieved evidence.
- Fairness audit metadata must capture candidate counts, result counts, top-5 local representation, missing geo-locality metadata, provider status, and user-safe warnings.

## Responsible AI Requirements

Responsible AI is implemented as internal quality controls:

- reliability through retrieval grounding and evals;
- fairness through deterministic re-ranking and audit metadata;
- robustness through guardrails, fallbacks, retries, and clear failure states;
- social impact through local-context metadata and accessibility support;
- explainability through citations, provider evidence, score breakdowns, and traces.

These controls should shape behavior and receipts. They should not be surfaced as five marketing axes in the core UX.
