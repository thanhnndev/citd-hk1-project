# Chat Soft-Strict Agent and UX Plan

## Goal

Make the chat behave like a production AI assistant: the model decides whether to answer directly, ask a clarification, or use a tool. The UI should show useful action state and evidence only when evidence exists. The five Responsible AI axes from `docs/REQUIREMENTS.md` must be implemented as behavior, not decorative labels.

## Requirements Mapping

| Axis | Behavior in Chat |
|---|---|
| Reliability | Conversational turns do not retrieve sources. Factual answers use relevant citations. Weak evidence triggers uncertainty or clarification. |
| Bias and Fairness | Place recommendations preserve local fairness and scoring metadata from the place service. |
| Robustness | Follow-up questions use conversation history. Ambiguous route/place requests ask clarifying questions instead of retrieving random chunks. |
| Social Impact | Commercial suggestions preserve local/community/accessibility context when returned by tools. |
| Explainability | Streaming emits safe status/trace events showing what the assistant is doing without exposing chain-of-thought. Sources and reasoning are collapsed by default. |

## TODO

- [x] Remove fake Responsible AI text badges from chat bubbles and footer status.
- [x] Add a real soft-strict agent service that lets the LLM choose: direct answer, clarification, knowledge search, or place/route search.
- [x] Keep fallback behavior safe: short follow-ups and conversational turns must not trigger RAG dumps when LLM is unavailable.
- [x] Stream status events (`[STATUS] understanding`, `using_history`, `searching_knowledge`, `checking_places`, `composing`) before/during answer generation.
- [x] Parse status events on the frontend and render them as transient AI activity state.
- [x] Collapse sources by default and show them only when citations are present.
- [x] Add AI disclosure text in the chat welcome/header.
- [x] Add tests for the reported failure sequence: `chào bạn` -> `bạn giúp được gì?` -> `4 nhóm gì?` -> no random citations.
- [x] Verify frontend type-check/lint and targeted backend tests.

## Acceptance Tests

1. `chào bạn` returns a direct conversational answer, no citations.
2. `bạn giúp được gì?` returns assistant capabilities, no citations.
3. After capabilities, `4 nhóm gì?` expands the previous capabilities, no citations.
4. `tìm đường thế nào?` asks for origin/destination or uses route/place tool when enough detail exists; it never returns unrelated RAG chunks.
5. Factual cultural questions call the knowledge tool and return collapsed citations.
6. Streaming shows what the AI is doing through status text, not decorative axis labels.
