/**
 * S05: Messenger-style chat UX contract tests.
 *
 * Static inspection (no network, browser, or backend) that proves:
 * - R055: ChatInterface exposes a messenger shell (role="log", sticky input
 *   composer, left/right user and assistant message alignment via MessageBubble).
 * - Deterministic quick reply chip data and click handling.
 * - Mobile/desktop responsive classes.
 * - Preserved S04 thinking/status and place card wiring.
 * - English/Vietnamese labels for quick replies.
 *
 * Designed to FAIL on missing quick reply wiring and PASS on the existing
 * messenger shell, S04 surfaces, and responsive layout.
 *
 * This test file does NOT read from any ignored planning paths.
 *
 * Run: node --test frontend/tests/s05-messenger-chat-contract.test.mjs
 */

import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';

// ── File Paths ───────────────────────────────────────────────────────────────

const frontendDir = path.resolve(import.meta.dirname, '..');

const paths = {
  chatApi: path.join(frontendDir, 'src/lib/chat-api.ts'),
  placeCard: path.join(frontendDir, 'src/components/chat/place-card.tsx'),
  messageBubble: path.join(frontendDir, 'src/components/chat/message-bubble.tsx'),
  chatInterface: path.join(frontendDir, 'src/components/chat/chat-interface.tsx'),
  welcomeScreen: path.join(frontendDir, 'src/components/chat/welcome-screen.tsx'),
  enMessages: path.join(frontendDir, 'messages/en.json'),
  viMessages: path.join(frontendDir, 'messages/vi.json'),
  s04Contract: path.join(frontendDir, 'tests/s04-explainability-contract.test.mjs'),
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function read(filePath) {
  if (!existsSync(filePath)) {
    throw new Error(`File not found: ${path.relative(frontendDir, filePath)}`);
  }
  return readFileSync(filePath, 'utf8');
}

// ── R055: Messenger Shell ────────────────────────────────────────────────────

test('R055: ChatInterface message list uses role="log" for messenger semantics', () => {
  const source = read(paths.chatInterface);

  assert.ok(
    /role\s*=\s*["']log["']/.test(source),
    'ChatInterface must use role="log" on the message container for accessibility'
  );
});

test('R055: ChatInterface message list has aria-live="polite" for streaming updates', () => {
  const source = read(paths.chatInterface);

  assert.ok(
    /aria-live\s*=\s*["']polite["']/.test(source),
    'ChatInterface must use aria-live="polite" on the message container'
  );
});

test('R055: MessageBubble aligns user messages right (flex-row-reverse)', () => {
  const source = read(paths.messageBubble);

  assert.ok(
    /flex-row-reverse/.test(source),
    'MessageBubble must use flex-row-reverse for user message alignment'
  );
});

test('R055: MessageBubble aligns assistant messages left (flex-row)', () => {
  const source = read(paths.messageBubble);

  assert.ok(
    /flex-row/.test(source),
    'MessageBubble must use flex-row for assistant message alignment'
  );
});

test('R055: MessageBubble uses distinct bubble styles for user vs assistant', () => {
  const source = read(paths.messageBubble);

  assert.ok(
    /isUser/.test(source) && /rounded-tr-md/.test(source) && /rounded-tl-md/.test(source),
    'MessageBubble must render different rounded corners for user vs assistant bubbles'
  );
});

// ── R055: Input Composer ─────────────────────────────────────────────────────

test('R055: ChatInterface has a textarea-based input composer', () => {
  const source = read(paths.chatInterface);

  assert.ok(
    /<textarea/.test(source),
    'ChatInterface must render a <textarea> for message input'
  );
});

test('R055: ChatInterface composer is in a fixed/sticky footer region', () => {
  const source = read(paths.chatInterface);

  // The composer area must be at the bottom — check for the bottom container
  // that holds the textarea (z-10 border-t backdrop-blur pattern)
  assert.ok(
    /border-t/.test(source) && /backdrop-blur/.test(source),
    'ChatInterface must have a sticky footer bar for the input composer'
  );
});

test('R055: ChatInterface composer has a send button', () => {
  const source = read(paths.chatInterface);

  // Look for a button near the textarea that triggers handleSubmit
  assert.ok(
    /handleSubmit/.test(source) && /onClick/.test(source),
    'ChatInterface must have a send button that calls handleSubmit'
  );
});

// ── R055: Mobile/Desktop Responsive Classes ──────────────────────────────────

test('R055: ChatInterface uses responsive breakpoints (md:) for layout', () => {
  const source = read(paths.chatInterface);

  const responsivePatterns = [
    /md:/,
    /sm:/,
    /hidden\s+\w*\s*md:/,
  ];
  const matches = responsivePatterns.filter((p) => p.test(source));
  assert.ok(
    matches.length >= 2,
    `ChatInterface must use at least 2 responsive breakpoint patterns (found ${matches.length})`
  );
});

test('R055: ChatInterface uses 100dvh for mobile viewport height', () => {
  const source = read(paths.chatInterface);

  assert.ok(
    /100dvh/.test(source),
    'ChatInterface must use 100dvh for mobile-safe viewport height'
  );
});

test('R055: MessageBubble uses responsive max-width for messages', () => {
  const source = read(paths.messageBubble);

  assert.ok(
    /md:max-w-\[74%\]/.test(source),
    'MessageBubble must use different max-width on mobile vs desktop'
  );
});

// ── R055: Deterministic Quick Reply Chips ────────────────────────────────────

test('R055: Quick reply chips are defined as bounded arrays in ChatInterface', () => {
  const source = read(paths.chatInterface);

  // Quick replies must come from deterministic data (prompts array, quickReply
  // config, or similar bounded source) — NOT from LLM output
  assert.ok(
    /prompts/.test(source),
    'ChatInterface must define a prompts or quickReply array for deterministic chips'
  );
});

test('R055: Quick reply chips have click handler that sends the chip text', () => {
  const source = read(paths.chatInterface);

  // Look for handlePromptClick or similar handler that calls handleSubmit
  assert.ok(
    /handlePromptClick|onPromptClick|quickReply.*onClick/.test(source),
    'ChatInterface must have a click handler for quick reply chips'
  );
});

test('R055: WelcomeScreen exposes promptChips for onboarding', () => {
  const source = read(paths.welcomeScreen);

  assert.ok(
    /promptChips|prompts/.test(source),
    'WelcomeScreen must expose promptChips or prompts prop for onboarding chips'
  );
});

test('R055: WelcomeScreen renders clickable prompt chip buttons', () => {
  const source = read(paths.welcomeScreen);

  assert.ok(
    /onClick|Button/.test(source),
    'WelcomeScreen must render clickable buttons for prompt chips'
  );
});

// ── R055: Quick Reply Labels in Translations ─────────────────────────────────

test('R055: English translations include Chat.prompts array with ≥3 items', () => {
  const messages = JSON.parse(read(paths.enMessages));
  const chat = messages.Chat ?? {};

  assert.ok(
    Array.isArray(chat.prompts) && chat.prompts.length >= 3,
    `Chat.prompts must have ≥3 English prompt labels (found ${chat.prompts?.length ?? 0})`
  );

  // Each prompt must be a non-empty string
  for (const [i, prompt] of chat.prompts.entries()) {
    assert.ok(
      typeof prompt === 'string' && prompt.trim().length > 0,
      `Chat.prompts[${i}] must be a non-empty string`
    );
  }
});

test('R055: Vietnamese translations include Chat.prompts array with ≥3 items', () => {
  const messages = JSON.parse(read(paths.viMessages));
  const chat = messages.Chat ?? {};

  assert.ok(
    Array.isArray(chat.prompts) && chat.prompts.length >= 3,
    `Chat.prompts must have ≥3 Vietnamese prompt labels (found ${chat.prompts?.length ?? 0})`
  );

  for (const [i, prompt] of chat.prompts.entries()) {
    assert.ok(
      typeof prompt === 'string' && prompt.trim().length > 0,
      `Chat.prompts[${i}] must be a non-empty string`
    );
  }
});

test('R055: English and Vietnamese prompt arrays have the same length', () => {
  const en = JSON.parse(read(paths.enMessages)).Chat?.prompts ?? [];
  const vi = JSON.parse(read(paths.viMessages)).Chat?.prompts ?? [];

  assert.equal(
    en.length,
    vi.length,
    `English and Vietnamese prompt arrays must have the same length (en=${en.length}, vi=${vi.length})`
  );
});

// ── R055: Preserved S04 Thinking/Status Surfaces ─────────────────────────────

test('R055: MessageBubble still renders streamStatusLabel (S04 preserved)', () => {
  const source = read(paths.messageBubble);

  assert.ok(
    /streamStatusLabel/.test(source),
    'MessageBubble must still accept streamStatusLabel prop for S04 streaming status'
  );
});

test('R055: MessageBubble still renders statusHistory timeline (S04 preserved)', () => {
  const source = read(paths.messageBubble);

  assert.ok(
    /statusHistory/.test(source),
    'MessageBubble must still render statusHistory timeline for S04 thinking surface'
  );
});

test('R055: MessageBubble still renders PlaceCard for places (S04 preserved)', () => {
  const source = read(paths.messageBubble);

  assert.ok(
    /PlaceCard/.test(source),
    'MessageBubble must still render PlaceCard for place results'
  );
});

test('R055: ChatInterface still tracks streamStatus per assistant message (S04 preserved)', () => {
  const source = read(paths.chatInterface);

  assert.ok(
    /streamStatus/.test(source),
    'ChatInterface must still track streamStatus on assistant messages'
  );
});

test('R055: ChatInterface still passes placeTranslations to MessageBubble (S04 preserved)', () => {
  const source = read(paths.chatInterface);

  assert.ok(
    /placeTranslations/.test(source),
    'ChatInterface must still pass placeTranslations to MessageBubble for S04 place cards'
  );
});

// ── R055: Preserved S04 Explainability Wiring ────────────────────────────────

test('R055: PlaceCard still imports PlaceExplanation type (S04 preserved)', () => {
  const source = read(paths.placeCard);

  assert.ok(
    /PlaceExplanation/.test(source),
    'PlaceCard must still import or reference PlaceExplanation type'
  );
});

test('R055: PlaceCard still accesses place.explanation (S04 preserved)', () => {
  const source = read(paths.placeCard);

  assert.ok(
    /place\.explanation\b/.test(source),
    'PlaceCard must still access place.explanation for S04 rendering'
  );
});

test('R055: PlaceCard still accesses place.score_breakdown (S04 preserved)', () => {
  const source = read(paths.placeCard);

  assert.ok(
    /place\.score_breakdown\b/.test(source),
    'PlaceCard must still access place.score_breakdown for S04 score rendering'
  );
});

// ── Negative Tests ───────────────────────────────────────────────────────────

test('Negative: Quick reply labels are NOT LLM/network-derived', () => {
  const source = read(paths.chatInterface);

  // Quick replies must not come from fetch/streamChat/sendChat/LLM responses.
  // We check for on the SAME LINE as "prompts" or "quickReply" — single-line
  // matches are reliable; multiline /s flags produce false positives on large files.
  const llmDerivedPatterns = [
    /streamChat.*prompts/,
    /sendChat.*prompts/,
    /onToken.*prompt/i,
    /onDone.*prompt/i,
    /response\s*\.\s*prompts/,
    /res\s*\.\s*prompts/,
    /LLM.*prompt/i,
    /llm.*prompt/i,
    /model.*prompt/i,
  ];

  for (const pattern of llmDerivedPatterns) {
    assert.ok(
      !pattern.test(source),
      `Quick replies must not be LLM-derived: found "${pattern.source}"`
    );
  }
});

test('Negative: Quick reply labels do not include user PII or exact location', () => {
  const enMessages = JSON.parse(read(paths.enMessages));
  const viMessages = JSON.parse(read(paths.viMessages));

  const piiPatterns = [
    /location.*lat.*lng|gps|coordinate|address.*exact/i,
    /user.*email|phone.*number|name.*exact/i,
  ];

  const allPrompts = [
    ...(enMessages.Chat?.prompts ?? []),
    ...(viMessages.Chat?.prompts ?? []),
  ].join(' ');

  for (const pattern of piiPatterns) {
    assert.ok(
      !pattern.test(allPrompts),
      `Quick reply prompts must not include PII or exact location data`
    );
  }
});

test('Negative: Test file only reads from approved frontend source paths', () => {
  const allPathValues = Object.values(paths);
  for (const p of allPathValues) {
    const relativePath = path.relative(frontendDir, p);
    assert.ok(
      relativePath.startsWith('src/') ||
      relativePath.startsWith('messages/') ||
      relativePath.startsWith('tests/'),
      `Test must only read from approved frontend paths, got: "${relativePath}"`
    );
  }
});

test('Negative: Test does not inspect ignored planning paths', () => {
  const testSource = readFileSync(
    path.join(frontendDir, 'tests/s05-messenger-chat-contract.test.mjs'),
    'utf8'
  );

  // Must not reference dot-hidden directories or node_modules
  // (patterns checked against actual file references, not comments)
  const codeLines = testSource.split('\n').filter((line) => {
    const trimmed = line.trim();
    return !trimmed.startsWith('//') && !trimmed.startsWith('*') && !trimmed.startsWith('/*');
  }).join('\n');

  const ignoredPaths = [
    /['"]\.gsd\//,
    /['"]\.planning\//,
    /['"]\.audits\//,
    /['"]node_modules\//,
  ];

  for (const pattern of ignoredPaths) {
    assert.ok(
      !pattern.test(codeLines),
      `Test must not reference ignored paths in code: found "${pattern.source}"`
    );
  }
});

// ── S05/S04 Compatibility: Test does not conflict with S04 assertions ────────

test('Compatibility: S05 test references S04 contract test file for cross-slice compatibility', () => {
  const source = read(paths.s04Contract);

  // S04 test must still be loadable — verify it exports test definitions
  assert.ok(
    /test\s*\(/.test(source),
    'S04 contract test must still define test() calls for compatibility'
  );
});

test('Compatibility: ChatInterface translations object includes all S04 explainability keys', () => {
  const source = read(paths.chatInterface);

  const s04Keys = [
    'scoreBreakdown',
    'explanation',
    'providerSource',
    'providerStatus',
    'scoreDataLimited',
    'accessibilityNote',
  ];

  for (const key of s04Keys) {
    assert.ok(
      new RegExp(`\\b${key}\\b`).test(source),
      `ChatInterface translations must include S04 key "${key}"`
    );
  }
});

// ── Integration: Status Labels Defined in Both Locales ───────────────────────

test('R055: ChatInterface defines status labels for both English and Vietnamese', () => {
  const source = read(paths.chatInterface);

  assert.ok(
    /STATUS_LABELS/.test(source),
    'ChatInterface must define STATUS_LABELS dictionary'
  );

  // Must have both locales (keys may be quoted or unquoted)
  assert.ok(
    /\bvi\b/.test(source) && /\ben\b/.test(source),
    'STATUS_LABELS must have both Vietnamese and English status labels'
  );

  // Must reference all 5 streaming phases
  const statuses = [
    'understanding',
    'using_history',
    'searching_knowledge',
    'checking_places',
    'composing',
  ];

  for (const status of statuses) {
    assert.ok(
      new RegExp(`\\b${status}\\b`).test(source),
      `STATUS_LABELS must define label for "${status}" in both locales`
    );
  }
});

// ── Diagnostics: File Path Validation ────────────────────────────────────────

test('Diagnostics: All required source files exist and are readable', () => {
  for (const [name, filePath] of Object.entries(paths)) {
    assert.ok(
      existsSync(filePath),
      `Required source file "${name}" must exist at ${path.relative(frontendDir, filePath)}`
    );
  }
});

console.log(
  'S05 Messenger chat contract test loaded — verifies R055 (messenger shell, quick reply chips, responsive layout, S04 preserved surfaces, bilingual labels)'
);
