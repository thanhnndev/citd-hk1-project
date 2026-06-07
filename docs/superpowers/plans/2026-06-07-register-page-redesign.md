# Register Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the registration page to match the approved Phu Quoc split-screen reference while keeping the backend contract unchanged.

**Architecture:** Add a registration-specific server shell for layout and localized content. Keep `RegisterForm` as the client owner of state and API behavior, adding only frontend confirmation-password validation before the existing `register({ username, email, password })` call.

**Tech Stack:** Next.js 16, React 19, TypeScript, Tailwind CSS 4, next-intl, Lucide React, Node contract tests, Playwright.

---

### Task 1: Add Failing Registration Contract

**Files:**
- Create: `frontend/tests/s09-register-ui-contract.test.mjs`

- [ ] Assert the route uses `RegisterShell`, the shell uses `lg:grid-cols-[40%_60%]`, the form contains `confirm_password`, and the API call remains `register({ username, email, password })`.
- [ ] Run `node tests/s09-register-ui-contract.test.mjs` and confirm failure because the dedicated shell and confirm-password field are absent.

### Task 2: Implement Registration UI

**Files:**
- Create: `frontend/src/components/auth/register-shell.tsx`
- Modify: `frontend/src/app/[locale]/auth/register/page.tsx`
- Modify: `frontend/src/components/auth/register-form.tsx`
- Modify: `frontend/messages/vi.json`
- Modify: `frontend/messages/en.json`

- [ ] Add localized supporting copy, hero copy, confirm-password labels, mismatch error, support, language, and help labels.
- [ ] Build the responsive registration shell using the existing local Phu Quoc image.
- [ ] Restyle all fields with underlined inputs and add independent visibility controls for password and confirmation.
- [ ] Validate matching passwords before setting loading state or calling the API.
- [ ] Keep the existing API request and OTP redirect unchanged.
- [ ] Run the contract test and confirm it passes.

### Task 3: Verify

**Files:**
- Modify: `frontend/tests/s08-login-visual-check.mjs`

- [ ] Extend visual smoke coverage to `/vi/auth/register`.
- [ ] Run TypeScript, focused ESLint, production build, responsive browser checks, and `tests/s07-auth-e2e.test.mjs`.
