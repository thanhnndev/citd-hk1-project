# Chat Page Redesign Design

## Goal

Redesign the chat page to closely match the supplied three-panel travel-assistant reference while preserving all existing chat behavior, API contracts, backend logic, localization, citations, place results, and error handling.

## Allowed Scope

Files may be changed only inside:

- `frontend/**`
- `docs/**`

Files outside those directories must not be modified.

The implementation must not modify:

- `backend/**`
- API request or response contracts
- Database or AI orchestration logic
- Homepage, authentication, architecture, map, or admin pages
- Shared site header components

## Design Direction

Use the supplied reference as the visual target: a compact Notion/Intercom-style workspace with thin borders, white and light-gray surfaces, Oceanic Blue actions, restrained shadows, and dense but readable information.

The existing React components and live API data remain authoritative. The supplied HTML is a visual reference, not an implementation to copy directly.

## Desktop Layout

The chat page uses a viewport-height workspace with three areas:

1. Left sidebar, approximately 220-240px wide.
2. Flexible center conversation area.
3. Right place-recommendation panel, approximately 340-380px wide.

The right panel is rendered only when the current conversation contains place results. No fake places are introduced.

### Left Sidebar

The sidebar contains:

- Hàm Ninh AI brand treatment.
- New-question action wired to the existing reset behavior.
- Static visual categories matching the reference.
- Recent conversation labels derived only from existing frontend state when available.
- Compact settings/help icons as non-destructive interface affordances.

Static category items do not trigger unsupported backend actions. They are presentation-only unless an existing frontend behavior already supports them.

### Center Conversation

The center area contains:

- Compact page title bar.
- Scrollable message history.
- User messages aligned right on a light-gray bubble.
- Assistant messages aligned left with a blue assistant icon.
- Existing answer content, markdown, citations, place evidence, confidence information, retry state, and feedback actions.
- Composer anchored at the bottom of the center area.

The existing submission, streaming/loading, retry, validation, and API error behavior remains unchanged.

### Markdown Rendering

Assistant responses must be rendered through the existing frontend dependency `react-markdown` instead of displaying the response as a raw string.

The renderer must support and style:

- Paragraphs and line spacing.
- `**bold**` and `*italic*` emphasis.
- Ordered and unordered lists.
- Headings at a compact chat-appropriate scale.
- Inline code and fenced code blocks.
- Blockquotes.
- Safe links that open external URLs with `rel="noopener noreferrer"`.

Raw HTML from model responses must not be enabled. No `rehype-raw` behavior is introduced.

Existing numbered citations such as `[1]` must remain interactive. Citation references should be converted into the current source-link treatment without breaking surrounding Markdown formatting.

User messages may remain plain text. Markdown parsing is required for assistant responses.

### Right Place Panel

The panel is shown only when `PlaceResult` data exists.

It contains:

- “Suggested places” heading.
- Existing place results rendered as compact vertical cards.
- Name, category, rating, shortened address, map link, and available explanatory data.
- Existing provider and score details remain available without exposing unnecessary technical detail by default.

Place images are displayed only when the existing frontend data model already provides a usable image URL. Otherwise, use a frontend-only local visual placeholder. No backend field is added.

## Responsive Layout

### Tablet

- Hide the persistent left sidebar behind a compact toggle or reduce it to an icon rail.
- Keep the conversation as the primary area.
- Move place results into a collapsible panel or stacked section controlled entirely in frontend state.

### Mobile

- Render one conversation column.
- Use a compact top bar with controls for navigation and place results.
- Show place results below the relevant assistant response or in a frontend drawer/sheet.
- Keep the composer reachable without horizontal overflow.
- Maintain a minimum practical touch target for interactive controls.

## Component Strategy

Primary files expected to change:

- `frontend/src/components/chat/chat-interface.tsx`
  - Owns the three-panel shell, responsive panel state, message area, and composer placement.
- `frontend/src/components/chat/message-bubble.tsx`
  - Restyles user and assistant messages, renders assistant Markdown, and preserves interactive citations.
- `frontend/src/components/chat/citation-card.tsx`
  - Adapts citations to the compact source treatment.
- `frontend/src/components/chat/message-actions.tsx`
  - Matches compact feedback controls.
- `frontend/src/components/chat/place-card.tsx`
  - Adds the compact right-panel card presentation using existing `PlaceResult`.
- `frontend/src/components/chat/welcome-screen.tsx`
  - Fits the empty conversation state into the new center workspace.

`frontend/src/app/[locale]/chat/page.tsx` should remain unchanged unless an existing translation already available in `Chat` must be passed through. New hardcoded user-facing copy should be avoided.

## Data And State

No new network requests are introduced.

The page continues using:

- Existing chat API client and response types.
- Existing `PlaceResult` values.
- Existing citation and score data.
- Existing `react-markdown` dependency.
- Existing locale translations.
- Existing message submission and retry handlers.

New state is limited to presentation concerns such as opening or closing the mobile sidebar and place panel.

## Error Handling

- Preserve current API and validation error messages.
- Keep retry actions functional.
- Empty place results do not render the right desktop panel.
- Missing optional place fields degrade gracefully.
- Missing images use a frontend-only placeholder.
- Loading and typing states remain announced accessibly.

## Accessibility

- Preserve semantic buttons and links.
- Icon-only controls require accessible labels.
- Side panels require meaningful labels.
- Keyboard focus remains visible.
- Mobile drawers must expose expanded state and support closing.
- Message status and typing feedback remain accessible to assistive technology.
- Color is not the only indicator for confidence, errors, or selected state.

## Testing

Focused frontend tests will verify:

- The chat route still passes the existing translation contract.
- The page uses a three-panel desktop shell.
- The place panel is conditional on real place results.
- Existing send, retry, citations, and place-map links remain wired.
- Bold text, lists, links, code, and citation references render correctly in assistant messages.
- No backend imports or backend file changes are introduced.
- TypeScript and focused ESLint pass.
- Production build passes.
- Desktop and mobile browser checks show no page errors or horizontal overflow.

Final scope verification must confirm that task changes exist only under `frontend/**` and `docs/**`.

## Acceptance Criteria

1. Desktop chat closely matches the supplied three-panel reference.
2. Existing chat requests and responses continue working without API changes.
3. The place panel uses existing `PlaceResult` data and appears only when data exists.
4. Mobile and tablet layouts remain usable without horizontal overflow.
5. Citations, retry, feedback, map links, loading states, and errors remain functional.
6. Assistant Markdown renders correctly without enabling raw HTML.
7. Shared header and unrelated pages are unchanged.
8. No file outside `frontend/**` and `docs/**` is modified by this task.
9. No backend file, endpoint, schema, or contract is changed.
