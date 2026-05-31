# M014-S05: Messenger-Style Chat Redesign — Verification Evidence

**Milestone:** M014 (Messenger Polish & Explainability)
**Slice:** S05 (Messenger-Style Chat Redesign)
**Date:** 2025-01-30
**Proof Level:** Static + type-level (credential-free). Integrated browser proof deferred to S06.

---

## What S05 Delivers

### Messenger Shell (`chat-interface.tsx`, 778 lines)

| Feature | Implementation | Test Proof |
|---------|---------------|------------|
| Message list | `role="log"` + `aria-live="polite"` for screen-reader streaming | ✅ R055 contract |
| Sticky footer composer | `border-t` + `backdrop-blur` bottom bar with `<textarea>` | ✅ R055 contract |
| Mobile viewport | `100dvh` for safe-area iOS/Android height | ✅ R055 contract |
| Responsive breakpoints | `md:` and `sm:` Tailwind breakpoints for layout shifts | ✅ R055 contract |
| Send button | `onClick` → `handleSubmit` wire | ✅ R055 contract |

### Message Bubbles (`message-bubble.tsx`)

| Feature | User messages | Assistant messages |
|---------|--------------|-------------------|
| Alignment | `flex-row-reverse` (right-aligned) | `flex-row` (left-aligned) |
| Corner radii | `rounded-tr-md` (flat top-right) | `rounded-tl-md` (flat top-left) |
| Styling | User gradient bubble | Frosted glass bubble |
| Max-width | Mobile: full, Desktop: `md:max-w-[74%]` | Same |
| Status label | `streamStatusLabel` prop threaded through | Same |
| Timeline | `statusHistory` timeline rendered | Same |
| Place cards | `PlaceCard` rendered with `placeTranslations` | Same |

### Deterministic Quick Reply Chips (`chat-interface.tsx`)

| Category | Description |
|----------|-------------|
| `prompts` array | Bounded, deterministic array — NOT LLM-derived |
| Click handling | `handlePromptClick` → `handleSubmit(chipText)` |
| Bilingual labels | `Chat.prompts` in both `en.json` and `vi.json` (≥3 items each, same length) |
| Loading gate | Chips hidden during active streaming/loading |
| No PII | No user email, phone, exact location, GPS coordinates in labels |

### Welcome Screen (`welcome-screen.tsx`, 56 lines)

- Exposes `promptChips` prop for onboarding quick-reply chips
- Renders clickable `Button` elements for each prompt

### S04 Preservation (no regressions)

| Surface | Preserved? | Evidence |
|---------|-----------|----------|
| `streamStatusLabel` per message | ✅ | S05 + S04 contract both pass |
| `statusHistory` timeline | ✅ | `message-bubble.tsx` still renders |
| `PlaceCard` with `place.explanation` | ✅ | S04 contract verifies 3+ fields rendered |
| `place.score_breakdown` axes | ✅ | 3+ user-facing axes rendered |
| `PlaceExplanation` type import | ✅ | `place-card.tsx` imports from `chat-api.ts` |
| STATUS_LABELS (5 phases × 2 locales) | ✅ | En + vi labels for all 5 phases |
| S04 explainability translation keys | ✅ | `scoreBreakdown`, `explanation`, `providerSource`, `providerStatus`, `scoreDataLimited`, `accessibilityNote` present in both locales |

---

## Verification Commands

```bash
# S05 messenger UX contract (34 tests)
node --test frontend/tests/s05-messenger-chat-contract.test.mjs

# S04 explainability regression (21 tests)
node --test frontend/tests/s04-explainability-contract.test.mjs

# TypeScript type-check
npm --prefix frontend run type-check

# Production build
npm --prefix frontend run build
```

---

## Verification Results

| Check | Result | Details |
|-------|--------|---------|
| S05 contract tests | ✅ 34/34 pass | 105ms |
| S04 contract tests | ✅ 21/21 pass | 108ms |
| `tsc --noEmit` | ✅ 0 errors | 2s |
| `next build` | ✅ clean | 14s |

---

## Implementation Notes

- **Tailwind CSS**: All styling uses utility classes (no custom CSS modules added). Responsive breakpoints use `sm:` and `md:` prefixes.
- **Next.js**: `chat-interface.tsx` remains a client component (`"use client"`) to manage streaming state and quick reply interactivity.
- **i18n**: Quick reply labels sourced from `Chat.prompts` array in `frontend/messages/{en,vi}.json`. Arrays must have equal length and ≥3 non-empty string items.
- **Accessibility**: `role="log"` on message list enables screen-reader message queue semantics; `aria-live="polite"` ensures new messages are announced without interrupting current speech.
- **Negative contracts**: Test suite verifies quick replies are NOT LLM-derived (no `streamChat.*prompts`, `sendChat.*prompts`, `response.prompts` patterns) and contain no PII.

---

## Known Limits

| Limit | Reason | Deferred To |
|-------|--------|-------------|
| Live browser rendering proof | Static tests only; no Playwright or viewport capture | S06 |
| Touch interaction on mobile | No real-device or simulator testing | S06 |
| Keyboard navigation (Tab, Enter, Escape) | Static contract checks presence, not focus order | S06 |
| Streaming animation smoothness | No runtime measurement | S06 |
| Dark mode contrast ratios | Tailwind classes present, no WCAG ratio verification | Future |

---

## Files Modified

| File | Lines | Description |
|------|-------|-------------|
| `frontend/src/components/chat/chat-interface.tsx` | 778 | Messenger shell, quick reply chips, STATUS_LABELS, responsive layout |
| `frontend/src/components/chat/message-bubble.tsx` | — | Gradient/frosted bubbles, left/right alignment, S04 preserved surfaces |
| `frontend/src/components/chat/welcome-screen.tsx` | 56 | `promptChips` prop for onboarding |
| `frontend/src/components/chat/place-card.tsx` | 257 | S04 place explanation (unchanged, verified preserved) |
| `frontend/messages/en.json` | — | `Chat.prompts` English labels |
| `frontend/messages/vi.json` | — | `Chat.prompts` Vietnamese labels |
| `frontend/tests/s05-messenger-chat-contract.test.mjs` | — | 34-pass static contract (T01) |
