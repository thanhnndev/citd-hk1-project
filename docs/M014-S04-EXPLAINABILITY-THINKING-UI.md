# M014-S04: Explainability and Thinking UI — Verification Evidence

**Milestone:** M014 (Messenger Polish & Explainability)
**Slice:** S04 (Explainability and Thinking UI)
**Date:** 2025-01-30
**Proof Level:** Static + type-level (credential-free). Live provider/browser proof deferred to S06.

---

## What S04 Renders

### PlaceCard — Score Breakdown

| Axis | Backend Field | User Label |
|------|--------------|------------|
| Locality | `score_breakdown.tree1_locality` | "Local" |
| Proximity | `score_breakdown.tree2_proximity` | "Proximity" |
| Quality | `score_breakdown.tree3_quality` | "Quality" |
| Fairness | `score_breakdown.delta1_fairness` | "Fairness" |
| Access | `score_breakdown.delta2_access` | "Access" |
| Final | `score_breakdown.final_score` | Score badge + `#rank` |

Each axis renders as a horizontal progress bar (0–100%). Fairness and access deltas are mapped to a 0.5-centered range.

### PlaceCard — Explanation Fields

| Field | Rendered? | Fallback |
|-------|-----------|----------|
| `primary_reason` | ✅ — paragraph text | — |
| `matched_preferences` | ✅ — chips (capped at 4) | Hidden if empty |
| `local_context` | ✅ — 📍 italic line | Hidden if "local signal unknown" |
| `fairness_note` | ✅ — italic line | — |
| `accessibility_note` | ✅ — ♿ italic line | Hidden if "accessibility metadata unknown" |
| `route_summary` | ✅ — 🧭 italic line | Hidden if "route metadata unavailable" |
| `provider_source` | ✅ — Source badge | Hidden if null |
| `provider_status` | ✅ — Status badge (green/amber) | Hidden if null |
| `evidence_fields_used` | ✅ — details/summary "Data used" | Hidden if empty |
| `rank` | ✅ — 0 when not ranked | — |

**Missing-data fallback:** When `explanation` is absent or has no `primary_reason`, the card shows "Limited scoring data available" (translated via `Chat.scoreDataLimited`).

**No fabricated rationale:** PlaceCard never generates why-this-place prose. All explanation text comes from `place.explanation` backend fields only.

### MessageBubble — Thinking Timeline

| State | Rendering |
|-------|-----------|
| During streaming | Teal-tinted panel with spinner, showing phase flow (e.g., "Understanding → Searching relevant sources → Checking places/routes → Composing the answer") |
| After completion | Muted border panel showing completed phases + data summary (e.g., "Completed via · Composing · 3 sources · 5 places") |
| Fallback response | Synthetic `["composing"]` history; summary shows "Completed via · Composing · fallback" |

Status history is **deduplicated** (consecutive identical statuses collapsed) and **bounded** to the 5 `ChatStreamStatus` values.

### MessageBubble — Live Status Badge

During streaming (`status !== "complete"`), a badge shows the current phase label with an icon (Clock3 for "submitted", Loader2 spinner for "streaming").

### Footer Status Bar

The chat footer shows the active processing phase during loading, or source count after completion.

---

## Translation Coverage

All explainability labels are present in both `messages/en.json` and `messages/vi.json`:

| Key | English | Vietnamese |
|-----|---------|------------|
| `Chat.scoreBreakdown` | "Score Breakdown" | "Chi tiết điểm số" |
| `Chat.explanation` | "Why this place?" | "Tại sao gợi ý này?" |
| `Chat.providerSource` | "Source" | "Nguồn dữ liệu" |
| `Chat.providerStatus` | "Status" | "Trạng thái" |
| `Chat.scoreDataLimited` | "Limited scoring data available" | "Dữ liệu chấm điểm hạn chế" |
| `Chat.accessibilityNote` | "Accessibility info" | "Thông tin tiếp cận" |

---

## Gate Results

| Gate | Command | Result | Notes |
|------|---------|--------|-------|
| S04 contract tests | `node --test frontend/tests/s04-explainability-contract.test.mjs` | ✅ 21/21 pass | R053 types+rendering, R054 status, negative tests |
| TypeScript | `npm --prefix frontend run type-check` | ✅ 0 errors | Full project type-check |
| Next.js build | `npm --prefix frontend run build` | ✅ success | All routes compile |
| Chat submit E2E | `node --test frontend/tests/s04-chat-submit.test.mjs` | ⏸ runtime_blocked | Requires dev server on localhost:3000; not a code issue |

---

## Files Changed in S04

| File | Tasks |
|------|-------|
| `frontend/src/app/[locale]/chat/page.tsx` | T02 — added 6 explainability translation keys |
| `frontend/src/components/chat/place-card.tsx` | T03 — added local_context + route_summary rendering |
| `frontend/src/components/chat/chat-interface.tsx` | T04 — statusHistory tracking, dedup, fallback history |
| `frontend/src/components/chat/message-bubble.tsx` | T04 — thinking timeline + post-response summary panel |

## Out of Scope for S04 (reserved for S06)

- Live provider credential verification
- Browser E2E proof with real SSE streaming
- End-to-end cited answer flow (requires running backend)
