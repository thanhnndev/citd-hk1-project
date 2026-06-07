# Homepage Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the technical long-form homepage with the supplied tourism-focused Ham Ninh landing page.

**Architecture:** Create one focused `TourismHomepage` server component composed of internal section helpers and locale-aware links. The localized route supplies one structured `Landing.homepage` object; older technical landing components remain untouched but are no longer mounted on `/[locale]`.

**Tech Stack:** Next.js 16, React 19, TypeScript, Tailwind CSS 4, next-intl, Lucide React, Node contract tests, Playwright.

---

### Task 1: Add Homepage Contract

**Files:**
- Create: `frontend/tests/s10-homepage-redesign-contract.test.mjs`

- [ ] Assert the route uses `TourismHomepage`.
- [ ] Assert the new component contains stable IDs for hero, stats, benefits, steps, and final CTA.
- [ ] Assert primary CTAs link to `/chat` and the hero uses a local image.
- [ ] Run the contract and confirm it fails before implementation.

### Task 2: Implement Homepage

**Files:**
- Create: `frontend/src/components/landing/tourism-homepage.tsx`
- Modify: `frontend/src/app/[locale]/page.tsx`
- Modify: `frontend/messages/vi.json`
- Modify: `frontend/messages/en.json`
- Create: `frontend/public/images/ham-ninh-homepage.jpg`

- [ ] Add localized structured homepage copy.
- [ ] Build responsive hero, stats, benefits, steps, CTA, and light footer.
- [ ] Replace the route composition with `TourismHomepage`.
- [ ] Keep all links locale-aware and preserve the global header.
- [ ] Run the contract until green.

### Task 3: Verify

**Files:**
- Create: `frontend/tests/s10-homepage-visual-check.mjs`

- [ ] Capture desktop and mobile screenshots.
- [ ] Assert no overflow, console errors, or failed page resources.
- [ ] Run TypeScript, focused lint, production build, navigation contracts, and auth E2E.
