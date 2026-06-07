# Login Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the localized login page as the approved Phu Quoc 40/60 split-screen experience without changing authentication behavior.

**Architecture:** Keep the login route as the server-side composition point and add a login-specific full-viewport shell that visually supersedes the shared site header. Keep `LoginForm` as the client-side owner of field state, API calls, token persistence, and redirect behavior. Extend existing locale messages for all new visible and accessible labels.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Tailwind CSS 4, next-intl, Lucide React, Node contract tests, Playwright E2E.

---

### Task 1: Add Login UI Contract

**Files:**
- Create: `frontend/tests/s08-login-ui-contract.test.mjs`

- [ ] **Step 1: Write the failing test**

Create a Node test that reads the login page, shell, form, and locale files and asserts:

```js
assert.match(loginPage, /LoginShell/);
assert.match(loginShell, /lg:grid-cols-\[40%_60%\]/);
assert.match(loginShell, /login-hero/);
assert.match(loginForm, /id="email"/);
assert.match(loginForm, /id="password"/);
assert.match(loginForm, /border-b/);
assert.match(viMessages, /"rememberLogin"/);
assert.match(enMessages, /"rememberLogin"/);
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node tests/s08-login-ui-contract.test.mjs`

Expected: FAIL because `LoginShell` and the split-layout markers do not exist.

### Task 2: Implement the Split-Screen Login

**Files:**
- Create: `frontend/src/components/auth/login-shell.tsx`
- Modify: `frontend/src/app/[locale]/auth/login/page.tsx`
- Modify: `frontend/src/components/auth/login-form.tsx`
- Modify: `frontend/messages/vi.json`
- Modify: `frontend/messages/en.json`

- [ ] **Step 1: Add localized copy**

Add login description, hero lines, remember-login, forgot-password, support, language, and help labels under `Auth.login` in both locale files.

- [ ] **Step 2: Build `LoginShell`**

Create a server-rendered full-screen shell with:

```tsx
<div className="fixed inset-0 z-[60] overflow-y-auto bg-white lg:grid lg:grid-cols-[40%_60%]">
```

The left panel owns brand, heading, form, and footer. The right panel owns the Phu Quoc cover image, overlays, and two-line headline. A compact image header is shown on small screens.

- [ ] **Step 3: Restyle `LoginForm`**

Keep the existing submit handler and IDs. Replace card-style controls with icon labels, bottom-border-only inputs, password visibility control, remember checkbox, forgot-password affordance, rectangular blue submit button, error state, and registration link.

- [ ] **Step 4: Compose the route**

Replace `AuthCard` on the login route with `LoginShell`, passing translated content and the existing `LoginForm`.

- [ ] **Step 5: Run the focused test**

Run: `node tests/s08-login-ui-contract.test.mjs`

Expected: PASS.

### Task 3: Verify Behavior and Presentation

**Files:**
- Modify only if verification finds a defect.

- [ ] **Step 1: Run static checks**

Run: `npm run type-check`

Expected: PASS with no TypeScript errors.

Run: `npm run lint`

Expected: PASS with no new lint errors.

- [ ] **Step 2: Run auth E2E**

Start the frontend and run: `node tests/s07-auth-e2e.test.mjs`

Expected: Existing register, verify, login, and admin flow passes.

- [ ] **Step 3: Browser verification**

Open `/vi/auth/login` at desktop and mobile viewport sizes. Confirm split ratio, image cropping, focus states, no horizontal overflow, usable mobile controls, and no console errors.
