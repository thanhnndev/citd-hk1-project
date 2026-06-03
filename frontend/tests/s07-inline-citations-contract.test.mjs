/**
 * Contract: assistant messages render interactive inline citation markers while
 * preserving the existing collapsible sources drawer.
 *
 * Run: node --test frontend/tests/s07-inline-citations-contract.test.mjs
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';

const frontendDir = path.resolve(import.meta.dirname, '..');
const messageBubblePath = path.join(frontendDir, 'src/components/chat/message-bubble.tsx');
const source = readFileSync(messageBubblePath, 'utf8');

test('assistant answer renders citation markers as interactive links', () => {
  assert.match(source, /function\s+RichMessageContent\b/, 'RichMessageContent must render message text with citation markers');
  assert.match(source, /content\.split\(\/\(\\\[\\d\+\\\]\)\/g\)/, 'message content must parse [n] citation markers');
  assert.match(source, /href=\{citation\.url\}/, 'citation marker should open source URL when available');
  assert.match(source, /href=\{`#\$\{citationAnchorId\(citationIndex\)\}`\}/, 'citation marker should jump to source drawer item when no URL exists');
  assert.match(source, /aria-label=\{`Open source/, 'interactive source links need accessible labels');
});

test('existing collapsible source drawer remains unchanged', () => {
  assert.match(source, /<details[\s\S]*aria-label=\{sourcesLabel\}/, 'sources drawer must remain a details element');
  assert.match(source, /<CitationCard\s+citation=\{citation\}\s+index=\{i \+ 1\}/, 'sources drawer must still render CitationCard entries');
  assert.match(source, /id=\{citationAnchorId\(i\)\}/, 'source drawer items need anchors for citation marker jumps');
});
