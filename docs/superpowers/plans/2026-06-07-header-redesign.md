# Header Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle only the global header to match the supplied Ham Ninh AI reference.

**Architecture:** Keep server-side translation loading in `SiteHeader`, move route-aware navigation markup into a focused client component, and restyle the existing locale and auth controls without changing their behavior.

**Tech Stack:** Next.js 16, React 19, next-intl, Tailwind CSS 4, Lucide React, Node contract tests, Playwright.

---

### Task 1: Header Contract

**Files:**
- Create: `frontend/tests/s11-header-redesign-contract.test.mjs`

- [ ] Assert the header uses a route-aware client nav.
- [ ] Assert the landmark SVG test ID, 64px height, active underline, and flat text links exist.
- [ ] Run and confirm failure before implementation.

### Task 2: Header Implementation

**Files:**
- Create: `frontend/src/components/layout/header-navigation.tsx`
- Modify: `frontend/src/components/layout/site-header.tsx`
- Modify: `frontend/src/components/layout/locale-switcher.tsx`
- Modify: `frontend/src/components/layout/auth-nav.tsx`

- [ ] Build the Ham Ninh landmark SVG logo.
- [ ] Add route-aware desktop navigation.
- [ ] Restyle language and auth actions.
- [ ] Preserve locale and authentication behavior.

### Task 3: Verify

**Files:**
- Create: `frontend/tests/s11-header-visual-check.mjs`

- [ ] Capture desktop/mobile homepage header screenshots.
- [ ] Run TypeScript, focused lint, build, navigation contract, and auth E2E.
