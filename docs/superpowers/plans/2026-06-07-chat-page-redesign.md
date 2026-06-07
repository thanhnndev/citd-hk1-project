# Chat Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the frontend chat experience as a responsive three-panel travel-assistant workspace and render assistant Markdown correctly without changing backend behavior or API contracts.

**Architecture:** Preserve `ChatInterface` as the owner of chat requests, streaming, retry, messages, and presentation state. Extract only the new left navigation and right place-results presentation into focused frontend components, while `MessageBubble` keeps message rendering and gains safe `react-markdown` support with interactive citations. All production and test changes remain under `frontend/**`; documentation remains under `docs/**`.

**Tech Stack:** Next.js 16, React 19, TypeScript 6, Tailwind CSS 4, next-intl, react-markdown, Lucide React, Node contract tests, Playwright.

---

## File Structure

- Modify: `frontend/src/components/chat/chat-interface.tsx`
  - Keeps all existing API calls and message state.
  - Owns responsive sidebar/place-panel visibility and the center workspace.
- Create: `frontend/src/components/chat/chat-sidebar.tsx`
  - Renders brand, new-question control, visual categories, and recent prompts.
- Create: `frontend/src/components/chat/place-results-panel.tsx`
  - Renders real `PlaceResult` values in the desktop right rail and mobile panel.
- Modify: `frontend/src/components/chat/message-bubble.tsx`
  - Restyles messages and renders safe Markdown with citation links.
- Modify: `frontend/src/components/chat/citation-card.tsx`
  - Uses compact source cards matching the reference.
- Modify: `frontend/src/components/chat/message-actions.tsx`
  - Uses compact feedback controls without changing copy/retry behavior.
- Modify: `frontend/src/components/chat/place-card.tsx`
  - Adds a compact panel variant while preserving map/details behavior.
- Modify: `frontend/src/components/chat/welcome-screen.tsx`
  - Fits the empty state into the new center panel.
- Verify unchanged unless translation plumbing is required: `frontend/src/app/[locale]/chat/page.tsx`
- Create: `frontend/tests/s13-chat-redesign-contract.test.mjs`
- Create: `frontend/tests/s13-chat-markdown-contract.test.mjs`
- Create: `frontend/tests/s13-chat-visual-check.mjs`
- Do not modify: `backend/**`
- Do not modify: unrelated frontend pages or shared header components.

### Task 1: Lock Scope And Chat Contracts

**Files:**
- Create: `frontend/tests/s13-chat-redesign-contract.test.mjs`
- Test: `frontend/tests/s13-chat-redesign-contract.test.mjs`

- [ ] **Step 1: Write the failing layout contract**

```js
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const page = await readFile(
  new URL("../src/app/[locale]/chat/page.tsx", import.meta.url),
  "utf8",
);
const chat = await readFile(
  new URL("../src/components/chat/chat-interface.tsx", import.meta.url),
  "utf8",
);
const sidebar = await readFile(
  new URL("../src/components/chat/chat-sidebar.tsx", import.meta.url),
  "utf8",
).catch(() => "");
const places = await readFile(
  new URL("../src/components/chat/place-results-panel.tsx", import.meta.url),
  "utf8",
).catch(() => "");

assert.match(page, /<ChatInterface locale=\{locale\} translations=\{translations\} \/>/);
assert.match(chat, /ChatSidebar/);
assert.match(chat, /PlaceResultsPanel/);
assert.match(chat, /lg:grid-cols-\[240px_minmax\(0,1fr\)_360px\]/);
assert.match(chat, /latestPlaces\.length > 0/);
assert.match(sidebar, /newQuestion/);
assert.match(places, /PlaceCard/);
assert.match(places, /PlaceResult/);
assert.doesNotMatch(chat + sidebar + places, /@\/.*backend|fetch\(|axios/);

console.log("S13 chat redesign contract passed.");
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
cd frontend
node tests/s13-chat-redesign-contract.test.mjs
```

Expected: FAIL because `chat-sidebar.tsx` and `place-results-panel.tsx` do not exist.

- [ ] **Step 3: Commit the failing contract**

```powershell
git add frontend/tests/s13-chat-redesign-contract.test.mjs
git commit -m "test: lock chat redesign contract"
```

### Task 2: Add Safe Markdown Rendering

**Files:**
- Create: `frontend/tests/s13-chat-markdown-contract.test.mjs`
- Modify: `frontend/src/components/chat/message-bubble.tsx`
- Test: `frontend/tests/s13-chat-markdown-contract.test.mjs`

- [ ] **Step 1: Write the failing Markdown contract**

```js
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const bubble = await readFile(
  new URL("../src/components/chat/message-bubble.tsx", import.meta.url),
  "utf8",
);

assert.match(bubble, /import ReactMarkdown from "react-markdown"/);
assert.match(bubble, /components=\{markdownComponents\}/);
assert.match(bubble, /transformCitationMarkers/);
assert.match(bubble, /strong:/);
assert.match(bubble, /ul:/);
assert.match(bubble, /ol:/);
assert.match(bubble, /code:/);
assert.match(bubble, /blockquote:/);
assert.match(bubble, /target="_blank"/);
assert.doesNotMatch(bubble, /rehypeRaw|rehype-raw/);

console.log("S13 chat markdown contract passed.");
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
node tests/s13-chat-markdown-contract.test.mjs
```

Expected: FAIL because `MessageBubble` currently renders raw strings.

- [ ] **Step 3: Import and configure ReactMarkdown**

Add:

```tsx
import ReactMarkdown, { type Components } from "react-markdown";
```

Define compact, accessible renderers:

```tsx
const markdownComponents: Components = {
  p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-current">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  ul: ({ children }) => <ul className="my-3 list-disc space-y-1 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="my-3 list-decimal space-y-1 pl-5">{children}</ol>,
  li: ({ children }) => <li className="pl-1">{children}</li>,
  h1: ({ children }) => <h3 className="mb-2 mt-4 text-lg font-semibold">{children}</h3>,
  h2: ({ children }) => <h3 className="mb-2 mt-4 text-base font-semibold">{children}</h3>,
  h3: ({ children }) => <h4 className="mb-2 mt-3 font-semibold">{children}</h4>,
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-2 border-[#2383e2] pl-3 text-[#5f5e5b]">
      {children}
    </blockquote>
  ),
  code: ({ className, children }) =>
    className ? (
      <code className="block overflow-x-auto rounded-lg bg-[#f7f7f5] p-3 font-mono text-xs">
        {children}
      </code>
    ) : (
      <code className="rounded bg-[#f7f7f5] px-1.5 py-0.5 font-mono text-[0.9em]">
        {children}
      </code>
    ),
  a: ({ href, children }) => (
    <a
      href={href}
      target={href?.startsWith("#") ? undefined : "_blank"}
      rel={href?.startsWith("#") ? undefined : "noopener noreferrer"}
      className="font-medium text-[#2383e2] underline underline-offset-2"
    >
      {children}
    </a>
  ),
};
```

- [ ] **Step 4: Preserve numbered citations through Markdown**

Replace raw `[n]` markers before parsing:

```tsx
function transformCitationMarkers(content: string, citations?: Citation[]) {
  if (!citations?.length) return content;

  return content.replace(/\[(\d+)\]/g, (marker, rawIndex) => {
    const index = Number(rawIndex) - 1;
    const citation = citations[index];
    if (!citation) return marker;
    return `[${rawIndex}](${citation.url || `#${citationAnchorId(index)}`})`;
  });
}
```

Render assistant content with:

```tsx
<ReactMarkdown components={markdownComponents}>
  {transformCitationMarkers(content, citations)}
</ReactMarkdown>
```

Keep user messages as plain text with `whitespace-pre-wrap`.

- [ ] **Step 5: Run the Markdown test**

Run:

```powershell
node tests/s13-chat-markdown-contract.test.mjs
npm run type-check
npx eslint src/components/chat/message-bubble.tsx
```

Expected: all commands exit with code 0.

- [ ] **Step 6: Commit Markdown rendering**

```powershell
git add frontend/src/components/chat/message-bubble.tsx frontend/tests/s13-chat-markdown-contract.test.mjs
git commit -m "fix: render assistant markdown safely"
```

### Task 3: Extract The Left Sidebar

**Files:**
- Create: `frontend/src/components/chat/chat-sidebar.tsx`
- Modify: `frontend/src/components/chat/chat-interface.tsx`
- Test: `frontend/tests/s13-chat-redesign-contract.test.mjs`

- [ ] **Step 1: Create the sidebar contract**

Define:

```tsx
interface ChatSidebarProps {
  newQuestion: string;
  recentQuestions: string[];
  onNewQuestion: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
}
```

- [ ] **Step 2: Implement the sidebar**

Build a 240px light-gray rail with:

- Hàm Ninh AI logo and brand.
- Existing `newQuestion` label wired to `onNewQuestion`.
- Four presentation-only category rows.
- Up to two recent user questions from `recentQuestions`.
- Settings/help icon buttons with accessible labels and no unsupported action.

Desktop container:

```tsx
<aside className="hidden h-full w-60 shrink-0 flex-col border-r border-[#e9e9e7] bg-[#f7f7f5] lg:flex">
```

Mobile overlay:

```tsx
<div
  className={mobileOpen ? "fixed inset-0 z-50 lg:hidden" : "hidden"}
  role="dialog"
  aria-modal="true"
  aria-label="Chat navigation"
>
```

- [ ] **Step 3: Derive recent questions without new persistence**

Inside `ChatInterface`:

```tsx
const recentQuestions = messages
  .filter((message) => message.role === "user")
  .map((message) => message.content)
  .slice(-2)
  .reverse();
```

Pass the existing conversation reset function to `onNewQuestion`.

- [ ] **Step 4: Run focused checks**

```powershell
node tests/s13-chat-redesign-contract.test.mjs
npm run type-check
npx eslint src/components/chat/chat-sidebar.tsx src/components/chat/chat-interface.tsx
```

Expected: contract may still fail only on the missing place panel; type-check and lint pass.

- [ ] **Step 5: Commit the sidebar**

```powershell
git add frontend/src/components/chat/chat-sidebar.tsx frontend/src/components/chat/chat-interface.tsx
git commit -m "feat: add responsive chat sidebar"
```

### Task 4: Extract The Conditional Place Panel

**Files:**
- Create: `frontend/src/components/chat/place-results-panel.tsx`
- Modify: `frontend/src/components/chat/chat-interface.tsx`
- Modify: `frontend/src/components/chat/message-bubble.tsx`
- Modify: `frontend/src/components/chat/place-card.tsx`
- Test: `frontend/tests/s13-chat-redesign-contract.test.mjs`

- [ ] **Step 1: Add a compact PlaceCard variant**

Extend props:

```tsx
interface PlaceCardProps {
  place: PlaceResult;
  rank?: number;
  variant?: "default" | "panel";
  translations: PlaceCardTranslations;
}
```

For `variant="panel"`, render a compact vertical card with category, name, rating, shortened address, explanation, and map link. Use only fields already present on `PlaceResult`.

- [ ] **Step 2: Create PlaceResultsPanel**

Define:

```tsx
interface PlaceResultsPanelProps {
  places: PlaceResult[];
  translations: PlaceCardTranslations & {
    placeResultsHeading: string;
  };
  mobileOpen: boolean;
  onMobileClose: () => void;
}
```

Return `null` when `places.length === 0`.

Desktop shell:

```tsx
<aside
  className="hidden h-full min-h-0 w-[360px] shrink-0 flex-col border-l border-[#e9e9e7] bg-white lg:flex"
  aria-label={translations.placeResultsHeading}
>
```

Render:

```tsx
{places.slice(0, 6).map((place, index) => (
  <PlaceCard
    key={place.place_id}
    place={place}
    rank={index + 1}
    variant="panel"
    translations={translations}
  />
))}
```

- [ ] **Step 3: Derive the latest real place results**

Inside `ChatInterface`:

```tsx
const latestPlaces =
  [...messages]
    .reverse()
    .find((message) => message.role === "assistant" && message.places?.length)
    ?.places ?? [];
```

Render the panel only with:

```tsx
{latestPlaces.length > 0 && (
  <PlaceResultsPanel
    places={latestPlaces}
    translations={placeTranslations}
    mobileOpen={placesOpen}
    onMobileClose={() => setPlacesOpen(false)}
  />
)}
```

- [ ] **Step 4: Avoid duplicate desktop place cards**

Add a presentation prop to `MessageBubble`:

```tsx
showInlinePlaces?: boolean;
```

Use `showInlinePlaces` for mobile/tablet inline results and hide duplicate inline cards at desktop width with responsive classes. Do not remove place data from messages.

- [ ] **Step 5: Run contract and type checks**

```powershell
node tests/s13-chat-redesign-contract.test.mjs
npm run type-check
npx eslint src/components/chat/place-results-panel.tsx src/components/chat/place-card.tsx src/components/chat/message-bubble.tsx src/components/chat/chat-interface.tsx
```

Expected:

```text
S13 chat redesign contract passed.
```

- [ ] **Step 6: Commit the place panel**

```powershell
git add frontend/src/components/chat/place-results-panel.tsx frontend/src/components/chat/place-card.tsx frontend/src/components/chat/message-bubble.tsx frontend/src/components/chat/chat-interface.tsx
git commit -m "feat: add conditional chat place panel"
```

### Task 5: Rebuild The Center Chat Workspace

**Files:**
- Modify: `frontend/src/components/chat/chat-interface.tsx`
- Modify: `frontend/src/components/chat/message-bubble.tsx`
- Modify: `frontend/src/components/chat/citation-card.tsx`
- Modify: `frontend/src/components/chat/message-actions.tsx`
- Modify: `frontend/src/components/chat/welcome-screen.tsx`

- [ ] **Step 1: Replace the page shell**

Use:

```tsx
<div className="h-[calc(100dvh-4rem)] min-h-[36rem] overflow-hidden bg-white text-[#37352f]">
  <div
    className={`grid h-full min-h-0 ${
      latestPlaces.length > 0
        ? "lg:grid-cols-[240px_minmax(0,1fr)_360px]"
        : "lg:grid-cols-[240px_minmax(0,1fr)]"
    }`}
  >
    <ChatSidebar />
    <main className="flex min-h-0 min-w-0 flex-col bg-white">
      {/* compact title bar, scroll area, composer */}
    </main>
    <PlaceResultsPanel />
  </div>
</div>
```

Do not introduce a new `SiteHeader` or alter the shared header.

- [ ] **Step 2: Build the compact chat title bar**

Include:

- Mobile menu button.
- Existing localized `translations.title`.
- Search/notification visuals with accessible labels.
- Mobile places button only when `latestPlaces.length > 0`.

Controls without implemented product behavior remain `type="button"` and must not issue network requests.

- [ ] **Step 3: Restyle messages**

Use light-gray user bubbles and white assistant cards:

```tsx
isUser
  ? "rounded-2xl rounded-tr-sm bg-[#f0f0f0] text-[#37352f]"
  : "rounded-xl border border-[#e9e9e7] bg-white text-[#37352f] shadow-sm"
```

Keep:

- Streaming cursor.
- Typing state.
- Retry.
- Accessibility/guardrail badge.
- Source count.
- Existing status history.

- [ ] **Step 4: Restyle citations and actions**

Citation card:

```tsx
className="rounded-md border border-[#e9e9e7] bg-white px-3 py-2 text-xs hover:bg-[#f7f7f5]"
```

Action row:

- Copy and retry retain current handlers.
- Use compact icon buttons.
- Keep accessible labels and copied state.

- [ ] **Step 5: Anchor and restyle the composer**

Keep the existing `<textarea>`, keyboard handler, submission function, disabled/loading behavior, and auto-resize logic.

Use:

```tsx
<footer className="shrink-0 border-t border-[#e9e9e7] bg-white px-4 pb-4 pt-3 sm:px-8">
  <div className="relative mx-auto max-w-4xl">
    <textarea className="min-h-12 w-full resize-none rounded-2xl border border-[#e9e9e7] bg-white py-3 pl-4 pr-14 text-sm shadow-sm focus:border-[#2383e2] focus:outline-none focus:ring-2 focus:ring-[#2383e2]/10" />
  </div>
</footer>
```

- [ ] **Step 6: Simplify the welcome screen**

Fit the empty state into the center panel using a maximum width near `48rem`, compact intent cards, and the existing localized prompts. Keep all existing prompt click handlers.

- [ ] **Step 7: Run focused verification**

```powershell
npm run type-check
npx eslint src/components/chat/chat-interface.tsx src/components/chat/message-bubble.tsx src/components/chat/citation-card.tsx src/components/chat/message-actions.tsx src/components/chat/place-card.tsx src/components/chat/place-results-panel.tsx src/components/chat/chat-sidebar.tsx src/components/chat/welcome-screen.tsx
node tests/s13-chat-redesign-contract.test.mjs
node tests/s13-chat-markdown-contract.test.mjs
```

Expected: all commands exit with code 0.

- [ ] **Step 8: Commit center workspace styling**

```powershell
git add frontend/src/components/chat
git commit -m "feat: redesign chat workspace"
```

### Task 6: Add Responsive Browser Verification

**Files:**
- Create: `frontend/tests/s13-chat-visual-check.mjs`
- Test: `frontend/tests/s13-chat-visual-check.mjs`

- [ ] **Step 1: Write the visual check**

```js
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium } from "@playwright/test";

const baseURL = process.env.BASE_URL ?? "http://127.0.0.1:3500";
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
const outputDir = new URL("../test-results/chat-ui/", import.meta.url);

await mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({
  headless: true,
  ...(executablePath ? { executablePath } : {}),
});

for (const check of [
  { name: "desktop", viewport: { width: 1440, height: 900 } },
  { name: "tablet", viewport: { width: 820, height: 1000 } },
  { name: "mobile", viewport: { width: 375, height: 812 } },
]) {
  const page = await browser.newPage({ viewport: check.viewport });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto(`${baseURL}/vi/chat`, { waitUntil: "networkidle" });
  await page.locator("main").waitFor({ state: "visible" });

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  assert.equal(overflow, false, `${check.name} must not overflow horizontally`);
  assert.deepEqual(errors, [], `${check.name} must not emit page errors`);

  await page.screenshot({
    path: new URL(`${check.name}.png`, outputDir),
    fullPage: true,
  });
  await page.close();
}

await browser.close();
console.log("S13 chat visual check passed.");
```

- [ ] **Step 2: Build and start the frontend**

```powershell
npm run build
npm run start -- --port 3500
```

Expected: production build succeeds and server is available at port 3500.

- [ ] **Step 3: Run the visual check with Edge**

```powershell
New-Item -ItemType Directory -Force .tmp | Out-Null
$env:TEMP="$PWD\.tmp"
$env:TMP="$PWD\.tmp"
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH="C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
node tests/s13-chat-visual-check.mjs
```

Expected:

```text
S13 chat visual check passed.
```

- [ ] **Step 4: Inspect screenshots**

Inspect:

- `frontend/test-results/chat-ui/desktop.png`
- `frontend/test-results/chat-ui/tablet.png`
- `frontend/test-results/chat-ui/mobile.png`

Confirm:

- Desktop shows the left rail and center chat.
- Right rail is absent before real place results exist.
- Tablet/mobile retain a reachable composer.
- No controls overlap the shared header.
- No horizontal overflow exists.

- [ ] **Step 5: Stop the local server**

Stop only the process listening on port `3500`.

- [ ] **Step 6: Commit the visual check**

```powershell
git add frontend/tests/s13-chat-visual-check.mjs
git commit -m "test: verify responsive chat redesign"
```

### Task 7: Final Scope And Regression Verification

**Files:**
- Verify: `frontend/src/components/chat/**`
- Verify unchanged: `frontend/src/app/[locale]/chat/page.tsx` unless translation plumbing was necessary
- Verify unchanged: `frontend/src/components/layout/**`
- Verify unchanged: `backend/**`

- [ ] **Step 1: Run all focused checks**

```powershell
cd frontend
node tests/s13-chat-redesign-contract.test.mjs
node tests/s13-chat-markdown-contract.test.mjs
npm run type-check
npx eslint src/components/chat src/app/[locale]/chat/page.tsx
npm run build
```

Expected: every command exits with code 0.

- [ ] **Step 2: Verify API code and backend are unchanged**

From repository root:

```powershell
git diff -- backend frontend/src/lib/chat-api.ts
```

Expected: no changes attributable to this task.

- [ ] **Step 3: Verify allowed directory scope**

Run:

```powershell
git diff --name-only
```

Review every path. Changes from this task must start with:

```text
frontend/
docs/
```

Do not revert unrelated pre-existing user changes.

- [ ] **Step 4: Review the final implementation diff**

```powershell
git diff -- frontend/src/components/chat frontend/src/app/[locale]/chat/page.tsx frontend/tests/s13-chat-redesign-contract.test.mjs frontend/tests/s13-chat-markdown-contract.test.mjs frontend/tests/s13-chat-visual-check.mjs
```

Confirm:

- Existing `sendChat` and `streamChat` calls were not changed.
- No new `fetch` or API endpoint was introduced.
- Place results come from existing message data.
- Markdown does not enable raw HTML.
- User messages remain plain text.
- Shared header and unrelated pages are absent from the task diff.

- [ ] **Step 5: Commit final test corrections if needed**

```powershell
git add frontend/src/components/chat frontend/tests/s13-chat-redesign-contract.test.mjs frontend/tests/s13-chat-markdown-contract.test.mjs frontend/tests/s13-chat-visual-check.mjs
git commit -m "test: finalize chat redesign verification"
```
