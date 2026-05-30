# Search Places Requirements Gap

## Purpose

This document captures the current gap between `search_places` behavior and `docs/REQUIREMENTS.md` so a new milestone can be planned without mixing tactical chat fixes with Responsible AI hardening work.

## Current State

`search_places` is now a real tool in the LangGraph-style chat flow:

```text
LLM decides -> tool_node executes search_places -> LLM/final response
```

It is no longer a RAG fallback path. Place cards are sourced from `PlaceRecommendationService`, which calls the backend Places provider seam, enriches candidates with routes when available, runs feature extraction and ensemble reranking, and returns structured `PlaceResult` objects.

Implemented basics:

- Server-side Places ownership; credentials stay in backend.
- `PlaceRecommendationService.recommend()` produces grounded `PlaceResult` objects.
- Route enrichment degrades gracefully if unavailable.
- Ensemble reranking exists via `FeatureExtractor` and `EnsembleReranker`.
- Response includes `score_breakdown`, `local_factor`, `accessibility_score`, and `accessibility_warning` fields.
- `search_places` does not return document citations.

## Gap Summary

`search_places` is functional, but not yet complete against the full Responsible AI and Places requirements. The missing work is not UI decoration or routing case additions; it is a tool contract hardening milestone.

## Requirement Gaps

### 1. Reliability

Source: `docs/REQUIREMENTS.md` sections 3.2, 7, 9.1, 11.3.

Current:

- Place results come from the Places provider seam and normalized models.
- Place cards are grounded in `PlaceResult` objects.

Gaps:

- No deterministic final answer composer that guarantees every named place in the natural-language response is a returned `PlaceResult`.
- No output validator that rejects or removes place names not present in tool results.
- No explicit contract tests proving `search_places` cannot hallucinate place names in text.
- No structured tool response schema for `search_places` beyond generic query text.

Needed:

- Add a `SearchPlacesToolResult` schema with `status`, `places`, `reasoning_log`, `provider_status`, and `warnings`.
- Compose place answers deterministically from returned places, or validate LLM text against returned place names.
- Add tests: place names in response text must be subset of returned `PlaceResult.display_name`.

### 2. Bias And Fairness

Source: `docs/REQUIREMENTS.md` sections 8 and 9.2.

Current:

- `local_factor` exists on candidates/results.
- `EnsembleReranker` includes locality tree and fairness correction.
- `ScoreBreakdown` exposes final score and tree/correction components.

Gaps:

- No guarantee that top-5 contains at least 40% local businesses (`local_factor > 0.5`) as required by BIAS-01.
- No post-rank balancing or explicit failure/warning when local coverage is impossible.
- Monthly fairness audit requirement is not active in the current `search_places` path.
- `local_factor` defaults can hide missing metadata instead of surfacing coverage gaps.

Needed:

- Add a fairness post-processor after reranking:
  - Target: top-5 local ratio >= 40% when enough local candidates exist.
  - If impossible, return an audit warning explaining candidate pool limitations.
- Add audit log entries for every `search_places` call:
  - candidate count
  - result count
  - top-5 local ratio
  - missing `local_factor` count
  - provider status
- Add tests for local-ratio enforcement and insufficient-local-candidate warnings.

### 3. Robustness

Source: `docs/REQUIREMENTS.md` section 9.3 and 7.5.

Current:

- Places provider errors return safe public messages.
- Routes enrichment degrades gracefully.
- Route service has a circuit breaker memory.

Gaps:

- Places API circuit breaker fallback to SQLite/internal cache is not implemented as described in section 7.5 and ROB-04.
- `search_places` tool timeout is not aligned with Maps Agent 10s node timeout requirement.
- No explicit `NodeTimeoutError` friendly handling for `search_places` tool execution.
- No proof that provider errors never fall back to RAG or invented place output.

Needed:

- Add Places candidate cache/internal fallback store.
- Add circuit breaker around Places text search, not only route enrichment.
- Set `search_places` node/tool timeout to 10s and return friendly status on timeout.
- Add tests:
  - provider timeout opens circuit
  - circuit-open uses fallback cache when available
  - circuit-open with no cache returns honest unavailable response
  - no RAG fallback for place failures

### 4. Social Impact

Source: `docs/REQUIREMENTS.md` section 9.4.

Current:

- `local_factor`, `price_level`, `accessibility_score`, and `accessibility_warning` fields exist.
- Route enrichment may improve distance-aware ranking.

Gaps:

- SOC-01 local metadata coverage >= 80% is not measured or enforced.
- SOC-02 accessibility warning is pass-through only; no guaranteed warning generation when wheelchair access is false or unknown and the place may be hard to access.
- SOC-03 budget/price filter is not implemented from chat/tool input.
- SOC-05 cultural context before commercial suggestions was lost during cleanup; `search_places` currently does not prepend cultural/community context.

Needed:

- Add metadata coverage reporting to `PlaceRecommendationService`.
- Generate accessibility warnings from candidate accessibility options and route/distance context.
- Extend tool args and chat request plumbing for budget/accessibility preferences:
  - `budget_filter`
  - `accessibility_required`
  - optional `user_location`
- Add cultural context composer for commercial suggestions:
  - Short non-RAG or RAG-backed local context before recommendations.
  - Must not create document citations unless knowledge retrieval is actually used.
- Add tests for budget, accessibility, and cultural-context requirements.

### 5. Explainability

Source: `docs/REQUIREMENTS.md` section 9.5.

Current:

- `PlaceResult.score_breakdown` exposes tree scores, bagging score, fairness/accessibility corrections, final score, and rank.
- `reasoning_log` exists but is currently a compact status string.

Gaps:

- Reasoning log is not rich enough for "Tại sao gợi ý này?".
- No structured explanation payload per place beyond raw score fields.
- Langfuse trace/tool call instrumentation is incomplete after agent cleanup.
- Requirement EXP-05 mentions `{rf_score, gbm_score, local_factor, final_score, rank}` while current code exposes the rule-based ensemble schema. This is either a documentation drift or API compatibility gap.

Needed:

- Add structured `recommendation_explanation` or improve `reasoning_log`:
  - provider source
  - query interpreted
  - ranking factors
  - fairness adjustment
  - accessibility adjustment
  - route/distance basis
- Add Langfuse spans/events around `search_places` tool calls.
- Decide whether to update `docs/REQUIREMENTS.md` EXP-05 to current rule-based ensemble fields or expose compatibility aliases.
- Add tests for explanation payload completeness.

## Proposed Milestone Scope

### Slice 1: Tool Contract And Deterministic Output

Goal: Make `search_places` return a typed tool result and prevent hallucinated place names.

Deliverables:

- `SearchPlacesToolResult` schema.
- Deterministic place answer composer or text validator.
- Tests proving no place name outside returned results appears in response.

### Slice 2: Fairness And Metadata Coverage

Goal: Enforce economic fairness requirements and audit local representation.

Deliverables:

- Top-5 local-ratio post-processor.
- Missing metadata coverage warning/audit.
- Fairness audit log for every place search.
- Tests for BIAS-01 and BIAS-04.

### Slice 3: Robustness And Provider Fallback

Goal: Make provider failures safe and requirement-compliant.

Deliverables:

- Places API circuit breaker.
- Internal cache/SQLite fallback for place candidates.
- 10s tool timeout with friendly unavailable response.
- Tests for timeout, circuit open, cache fallback, and no RAG fallback.

### Slice 4: Social Impact Preferences

Goal: Support budget/accessibility and local context as real behavior.

Deliverables:

- Budget/accessibility/user-location args through chat -> tool -> reranker.
- Accessibility warning generator.
- Cultural/community context for commercial suggestions.
- Tests for SOC-02, SOC-03, SOC-05.

### Slice 5: Explainability And Observability

Goal: Make recommendations inspectable and traceable.

Deliverables:

- Structured explanation payload or expanded reasoning log.
- Langfuse spans for tool decision, Places call, route enrichment, reranking.
- EXP-05 docs/code alignment decision.
- Tests for explanation fields and trace emission.

## Acceptance Criteria For New Milestone

- Place discovery requests never use RAG as fallback.
- All place cards come from `PlaceResult` returned by `PlaceRecommendationService`.
- Natural-language place names are validated against returned `PlaceResult.display_name`.
- Top-5 local ratio is >= 40% when enough local candidates exist, otherwise a clear audit warning is recorded.
- Budget and accessibility preferences affect ranking/filtering.
- Places provider timeout/error returns an honest unavailable/cache-fallback response, not invented recommendations.
- Every `search_places` response includes enough structured explanation for the UI to answer "why this recommendation?".
- Tests cover all five Responsible AI axes for `search_places`.

## Out Of Scope For This Milestone

- Payment or booking flow.
- Browser-side direct Places/Routes calls.
- Training a learned ranking model.
- Rewriting RAG cultural answer generation, except where cultural context is intentionally composed for commercial suggestions.
