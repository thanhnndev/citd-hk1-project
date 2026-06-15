# Mobile Chat Drawers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the mobile chat sidebar and evidence panel reliably open and close from their trigger, close button, and backdrop.

**Architecture:** Keep drawer state owned by `ChatInterface`. In each drawer component, render a full-screen dialog container with an explicit backdrop button beneath a higher-z-index panel so pointer events reach the intended control.

**Tech Stack:** Next.js 16, React 19, Tailwind CSS, Playwright.

---

### Task 1: Add Mobile Drawer Regression Coverage

**Files:**
- Create: `frontend/tests/s13-chat-mobile-drawers.test.mjs`

- [ ] Write a Playwright test at a 375x812 touch viewport that opens and closes the sidebar from its trigger, close button, and backdrop.
- [ ] Mock a chat response containing citations, submit a message, then open and close the evidence panel from its trigger, close button, and backdrop.
- [ ] Run `node tests/s13-chat-mobile-drawers.test.mjs` and confirm it fails because current mobile overlay structure intercepts or misses the expected close interaction.

### Task 2: Fix Drawer Layering And Backdrops

**Files:**
- Modify: `frontend/src/components/chat/chat-sidebar.tsx`
- Modify: `frontend/src/components/chat/place-results-panel.tsx`

- [ ] Give each mobile backdrop its own full-screen button with `z-0`.
- [ ] Give each drawer panel `relative z-10` so its controls remain above the backdrop.
- [ ] Add the missing evidence-panel backdrop close button.
- [ ] Keep existing state callbacks and desktop rendering unchanged.
- [ ] Run the mobile drawer test and confirm all open/close paths pass.

### Task 3: Verify

**Files:**
- Test: `frontend/tests/s13-chat-mobile-drawers.test.mjs`
- Test: `frontend/tests/s13-chat-redesign-contract.test.mjs`

- [ ] Run the focused Playwright test.
- [ ] Run the chat redesign contract test.
- [ ] Run `npm run type-check`.
- [ ] Run ESLint only on changed files.
