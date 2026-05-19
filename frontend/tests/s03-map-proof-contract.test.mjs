import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';

const frontendDir = path.resolve(import.meta.dirname, '..');
const componentPath = path.join(frontendDir, 'src/components/map/place-proof-map.tsx');
const pagePath = path.join(frontendDir, 'src/app/[locale]/map/page.tsx');
const enMessagesPath = path.join(frontendDir, 'messages/en.json');
const viMessagesPath = path.join(frontendDir, 'messages/vi.json');

function read(relPath) {
  return readFileSync(relPath, 'utf8');
}

test('/map route renders PlaceProofMap instead of placeholder', () => {
  const page = read(pagePath);
  assert.match(page, /PlaceProofMap/);
  assert.doesNotMatch(page, /PlaceholderPage/);
  assert.match(page, /setRequestLocale\(locale\)/);
  assert.match(page, /notFound\(\)/);
});

test('PlaceProofMap delegates recommendation intelligence only to /api/chat client', () => {
  const source = read(componentPath);
  assert.match(source, /sendChat\(/);
  assert.doesNotMatch(source, /places\.googleapis\.com/i);
  assert.doesNotMatch(source, /google\.maps\.places/i);
  assert.doesNotMatch(source, /NEXT_PUBLIC_.*(MAP|PLACE|GOOGLE|KEY)/i);
});

test('PlaceProofMap exposes failure, empty, fallback, pin, detail, and Maps-link states', () => {
  const source = read(componentPath);
  for (const token of [
    'unavailable',
    'noResults',
    'fallback',
    'pinUnavailable',
    'google_maps_uri',
    'rating',
    'user_rating_count',
    'open_now',
    'business_status',
    'accessibility_score',
    'location.lat',
    'location.lng',
  ]) {
    assert.ok(source.includes(token), `component must include ${token}`);
  }
});

test('Map message catalogs include matching proof-surface keys', () => {
  const requiredKeys = [
    'title', 'intro', 'defaultQuery', 'queryLabel', 'searchPlaceholder', 'submit',
    'loading', 'error', 'unavailable', 'noResults', 'fallback', 'resultCount',
    'detailTitle', 'selectPlace', 'pinReady', 'pinUnavailable', 'mapsLink',
    'rating', 'reviews', 'openNow', 'closedNow', 'openUnknown', 'businessStatus',
    'type', 'accessibility', 'address', 'coordinates', 'unknown', 'responseNote',
  ];

  for (const messagePath of [enMessagesPath, viMessagesPath]) {
    const mapMessages = JSON.parse(read(messagePath)).Map;
    for (const key of requiredKeys) {
      assert.equal(typeof mapMessages[key], 'string', `${messagePath} Map.${key} must be a string`);
      assert.ok(mapMessages[key].length > 0, `${messagePath} Map.${key} must not be empty`);
    }
  }
});

console.log('S03 Map proof contract test loaded — verifies localized backend-only place proof surface');
