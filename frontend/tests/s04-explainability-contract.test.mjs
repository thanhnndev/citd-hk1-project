/**
 * S04: Frontend explainability and thinking UI contract tests.
 *
 * Static inspection (no network, browser, or backend) that proves:
 * - R053: PlaceExplanation type with all 11 backend fields, ScoreBreakdown
 *   axis rendering, provider/evidence labels, and missing-data fallbacks.
 * - R054: Live streaming status labels and post-response status summaries.
 *
 * Designed to FAIL against the current minimal card (pre-S04) and PASS
 * only after T02 (types + translations), T03 (score + explanation rendering),
 * and T04 (thinking timeline + status summary) are complete.
 *
 * This test file does NOT read from any ignored planning paths.
 *
 * Run: node --test frontend/tests/s04-explainability-contract.test.mjs
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
  enMessages: path.join(frontendDir, 'messages/en.json'),
  viMessages: path.join(frontendDir, 'messages/vi.json'),
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function read(filePath) {
  if (!existsSync(filePath)) {
    throw new Error(`File not found: ${path.relative(frontendDir, filePath)}`);
  }
  return readFileSync(filePath, 'utf8');
}

// ── Schema Definitions ───────────────────────────────────────────────────────

const PLACE_EXPLANATION_FIELDS = [
  'rank',
  'primary_reason',
  'matched_preferences',
  'local_context',
  'score_factors',
  'fairness_note',
  'accessibility_note',
  'route_summary',
  'provider_source',
  'provider_status',
  'evidence_fields_used',
];

const SCORE_BREAKDOWN_AXES = [
  'tree1_locality',
  'tree2_proximity',
  'tree3_quality',
  's_bag',
  'delta1_fairness',
  'delta2_access',
  'final_score',
  'rank',
];

const CHAT_STREAM_STATUSES = [
  'understanding',
  'using_history',
  'searching_knowledge',
  'checking_places',
  'composing',
];

const PROVIDER_SOURCES = ['google_places', 'goong_places', 'mock', 'cache'];
const PROVIDER_STATUSES = ['ok', 'empty', 'credentials_blocked', 'upstream_error', 'unavailable'];

// ── R053: PlaceExplanation Type Contract (T02) ──────────────────────────────

test('R053: chat-api.ts declares PlaceExplanation with all 11 backend fields', () => {
  const source = read(paths.chatApi);

  assert.ok(
    /export\s+interface\s+PlaceExplanation\b/.test(source),
    'PlaceExplanation interface must be exported from chat-api.ts'
  );

  for (const field of PLACE_EXPLANATION_FIELDS) {
    assert.ok(
      new RegExp(`\\b${field}\\b`).test(source),
      `PlaceExplanation must declare field "${field}"`
    );
  }
});

test('R053: PlaceResult includes explanation?: PlaceExplanation', () => {
  const source = read(paths.chatApi);

  assert.ok(
    /export\s+interface\s+PlaceResult\b/.test(source),
    'PlaceResult interface must exist in chat-api.ts'
  );

  assert.ok(
    /\bexplanation\b/.test(source) && /\bPlaceExplanation\b/.test(source),
    'PlaceResult must reference PlaceExplanation via an explanation field'
  );
});

test('R053: ScoreBreakdown declares all 8 ensemble scoring fields', () => {
  const source = read(paths.chatApi);

  assert.ok(
    /export\s+interface\s+ScoreBreakdown\b/.test(source),
    'ScoreBreakdown interface must be exported from chat-api.ts'
  );

  for (const field of SCORE_BREAKDOWN_AXES) {
    assert.ok(
      new RegExp(`\\b${field}\\b`).test(source),
      `ScoreBreakdown must declare field "${field}"`
    );
  }
});

// ── R053: Score Breakdown Rendering (T03) ────────────────────────────────────

test('R053: PlaceCard component renders score breakdown axes', () => {
  const source = read(paths.placeCard);

  // Must reference score_breakdown on the place object
  assert.ok(
    /place\.score_breakdown\b/.test(source),
    'PlaceCard must access place.score_breakdown for axis rendering'
  );

  // At least 3 of the 5 user-facing axes must be rendered
  const userFacingAxes = ['tree1_locality', 'tree2_proximity', 'tree3_quality', 'delta1_fairness', 'delta2_access'];
  const renderedAxes = userFacingAxes.filter((axis) =>
    new RegExp(`score_breakdown\\.${axis}\\b`).test(source)
  );
  assert.ok(
    renderedAxes.length >= 3,
    `PlaceCard must render at least 3 of 5 user-facing score axes (found ${renderedAxes.length}: ${renderedAxes.join(', ')})`
  );
});

test('R053: PlaceCard renders final_score and rank from score_breakdown', () => {
  const source = read(paths.placeCard);

  assert.ok(
    /score_breakdown\.(?:final_score|rank)\b/.test(source),
    'PlaceCard must render final_score or rank from score_breakdown'
  );
});

// ── R053: Explanation Rendering (T03) ────────────────────────────────────────

test('R053: PlaceCard imports PlaceExplanation type from chat-api', () => {
  const source = read(paths.placeCard);

  assert.ok(
    /PlaceExplanation/.test(source),
    'PlaceCard must import or reference PlaceExplanation type'
  );
});

test('R053: PlaceCard renders explanation fields from place.explanation', () => {
  const source = read(paths.placeCard);

  assert.ok(
    /place\.explanation\b/.test(source),
    'PlaceCard must access place.explanation for rendering'
  );

  // At least 3 explanation fields must be rendered
  const explanationFields = [
    'primary_reason', 'matched_preferences', 'local_context', 'score_factors',
    'fairness_note', 'accessibility_note', 'route_summary',
    'provider_source', 'provider_status', 'evidence_fields_used',
  ];
  const renderedFields = explanationFields.filter((field) =>
    new RegExp(`explanation\\.${field}\\b`).test(source)
  );
  assert.ok(
    renderedFields.length >= 3,
    `PlaceCard must render at least 3 explanation fields (found ${renderedFields.length}: ${renderedFields.join(', ')})`
  );
});

// ── R053: Provider & Evidence Labels in Translations ─────────────────────────

test('R053: English translations include explainability labels', () => {
  const messages = JSON.parse(read(paths.enMessages));
  const chat = messages.Chat ?? {};

  // Score breakdown label
  assert.ok(
    typeof chat.scoreBreakdown === 'string' && chat.scoreBreakdown.length > 0,
    'Chat.scoreBreakdown must have an English label'
  );

  // Explanation section label
  assert.ok(
    typeof chat.explanation === 'string' && chat.explanation.length > 0,
    'Chat.explanation must have an English label'
  );

  // Provider source label
  assert.ok(
    typeof chat.providerSource === 'string' && chat.providerSource.length > 0,
    'Chat.providerSource must have an English label'
  );

  // Provider status label
  assert.ok(
    typeof chat.providerStatus === 'string' && chat.providerStatus.length > 0,
    'Chat.providerStatus must have an English label'
  );

  // Missing data fallback label
  assert.ok(
    typeof chat.scoreDataLimited === 'string' && chat.scoreDataLimited.length > 0,
    'Chat.scoreDataLimited must have an English label for missing data fallback'
  );

  // Accessibility note label
  assert.ok(
    typeof chat.accessibilityNote === 'string' && chat.accessibilityNote.length > 0,
    'Chat.accessibilityNote must have an English label'
  );
});

test('R053: Vietnamese translations include explainability labels', () => {
  const messages = JSON.parse(read(paths.viMessages));
  const chat = messages.Chat ?? {};

  assert.ok(
    typeof chat.scoreBreakdown === 'string' && chat.scoreBreakdown.length > 0,
    'Chat.scoreBreakdown must have a Vietnamese label'
  );

  assert.ok(
    typeof chat.explanation === 'string' && chat.explanation.length > 0,
    'Chat.explanation must have a Vietnamese label'
  );

  assert.ok(
    typeof chat.providerSource === 'string' && chat.providerSource.length > 0,
    'Chat.providerSource must have a Vietnamese label'
  );

  assert.ok(
    typeof chat.providerStatus === 'string' && chat.providerStatus.length > 0,
    'Chat.providerStatus must have a Vietnamese label'
  );

  assert.ok(
    typeof chat.scoreDataLimited === 'string' && chat.scoreDataLimited.length > 0,
    'Chat.scoreDataLimited must have a Vietnamese label for missing data fallback'
  );

  assert.ok(
    typeof chat.accessibilityNote === 'string' && chat.accessibilityNote.length > 0,
    'Chat.accessibilityNote must have a Vietnamese label'
  );
});

// ── R054: Streaming Status (T01 already exists, T04 enhances) ───────────────

test('R054: MessageBubble renders live streaming status during response', () => {
  const source = read(paths.messageBubble);

  // Must show status badge when status != "complete"
  assert.ok(
    /streamStatusLabel/.test(source),
    'MessageBubble must accept streamStatusLabel prop for live status display'
  );

  // Must show status for both "submitted" and "streaming" states
  assert.ok(
    /status\s*===?\s*["']submitted["']/.test(source) ||
    /status\s*===?\s*["']streaming["']/.test(source),
    'MessageBubble must handle submitted/streaming status states'
  );
});

test('R054: MessageBubble accepts status prop with streaming states', () => {
  const source = read(paths.messageBubble);

  assert.ok(
    /\bstatus\b/.test(source) &&
    (/streaming/.test(source) || /submitted/.test(source)),
    'MessageBubble must handle streaming and submitted status values'
  );
});

// ── R054: Post-Response Status Summary (T04) ─────────────────────────────────

test('R054: ChatInterface tracks streamStatus per assistant message', () => {
  const source = read(paths.chatInterface);

  assert.ok(
    /streamStatus/.test(source),
    'ChatInterface must track streamStatus on assistant messages'
  );
});

test('R054: ChatInterface imports ChatStreamStatus type', () => {
  const source = read(paths.chatInterface);

  assert.ok(
    /ChatStreamStatus/.test(source),
    'ChatInterface must import ChatStreamStatus type from chat-api'
  );
});

test('R054: ChatInterface defines status labels for all 5 stream phases', () => {
  const source = read(paths.chatInterface);

  for (const status of CHAT_STREAM_STATUSES) {
    assert.ok(
      new RegExp(`\\b${status}\\b`).test(source),
      `ChatInterface must define label for status "${status}"`
    );
  }
});

test('R054: ChatInterface passes status labels to MessageBubble', () => {
  const source = read(paths.chatInterface);

  assert.ok(
    /streamStatusLabel/.test(source),
    'ChatInterface must pass streamStatusLabel to MessageBubble'
  );
});

test('R054: ChatInterface footer status bar shows active processing state', () => {
  const source = read(paths.chatInterface);

  // Footer status bar shows activeStatus during loading
  assert.ok(
    /activeStatus/.test(source),
    'ChatInterface must compute and display activeStatus in footer'
  );
});

// ── Negative Tests ───────────────────────────────────────────────────────────

test('Negative: PlaceCard does not fabricate why-this-place prose without explanation', () => {
  const source = read(paths.placeCard);

  // Must not contain hardcoded rationale that invents reasons
  const fabricatedPatterns = [
    /because\s+(this|it|the)\s+(place|restaurant|location)/i,
    /recommended\s+because/i,
    /we\s+recommend\s+this/i,
    /great\s+choice\s+because/i,
    /perfect\s+for\s+you\s+because/i,
  ];

  for (const pattern of fabricatedPatterns) {
    assert.ok(
      !pattern.test(source),
      `PlaceCard must not fabricate rationale: found "${pattern.source}"`
    );
  }
});

test('Negative: PlaceCard uses honest fallback for missing explanation data', () => {
  const source = read(paths.placeCard);

  // If explanation is rendered, missing-data fallback should use honest labels
  // not generic positive spin. Check that any conditional on explanation uses
  // the translation-based fallback pattern, not hardcoded optimistic text.
  if (/place\.explanation\b/.test(source)) {
    // Has explanation rendering — verify it doesn't use fabricated fallbacks
    const optimisticFallbacks = [
      /excellent\s+choice/i,
      /highly\s+recommended/i,
      /perfect\s+match/i,
      /we\s+think\s+you['']ll\s+love/i,
    ];
    for (const pattern of optimisticFallbacks) {
      assert.ok(
        !pattern.test(source),
        `PlaceCard must not use optimistic fallback: found "${pattern.source}"`
      );
    }
  }
  // If no explanation rendering yet, this test vacuously passes
});

test('Negative: Test file only reads from approved frontend source paths', () => {
  // Verify that all file paths in the paths object point to approved locations
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

test('Negative: Test does not contain fabricated frontend rationale literals', () => {
  const testSource = readFileSync(
    path.join(frontendDir, 'tests/s04-explainability-contract.test.mjs'),
    'utf8'
  );

  // Test must not define its own explanation text that could be confused
  // with actual backend explanation data
  const fabricatedLiterals = [
    /["']Great local restaurant["']/i,
    /["']Perfect match for your preferences["']/i,
    /["']We highly recommend this place["']/i,
  ];

  for (const pattern of fabricatedLiterals) {
    assert.ok(
      !pattern.test(testSource),
      `Test must not contain fabricated rationale literal: found "${pattern.source}"`
    );
  }
});

// ── Integration: Provider Status Vocabulary ──────────────────────────────────

test('R053: chat-api.ts or components reference provider status vocabulary', () => {
  // At least one frontend file must acknowledge the provider status values
  const sources = [
    read(paths.chatApi),
    read(paths.placeCard),
    read(paths.messageBubble),
  ].join('\n');

  // Check for at least 3 of the 5 provider status values
  const matchedStatuses = PROVIDER_STATUSES.filter((status) =>
    new RegExp(`\\b${status}\\b`).test(sources)
  );

  assert.ok(
    matchedStatuses.length >= 3,
    `Frontend must reference at least 3 provider status values (found ${matchedStatuses.length}: ${matchedStatuses.join(', ')})`
  );
});

console.log(
  'S04 Explainability contract test loaded — verifies R053 (score axes, explanation, provider labels, missing-data fallbacks) and R054 (streaming status, post-response summary)'
);
