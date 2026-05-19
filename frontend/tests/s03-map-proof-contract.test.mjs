import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';

const frontendDir = path.resolve(import.meta.dirname, '..');
const componentPath = path.join(frontendDir, 'src/components/map/place-proof-map.tsx');
const pagePath = path.join(frontendDir, 'src/app/[locale]/map/page.tsx');
const chatApiPath = path.join(frontendDir, 'src/lib/chat-api.ts');
const apiRoutePath = path.join(frontendDir, 'src/app/api/chat/route.ts');
const enMessagesPath = path.join(frontendDir, 'messages/en.json');
const viMessagesPath = path.join(frontendDir, 'messages/vi.json');

const requiredMapKeys = [
  'title', 'intro', 'defaultQuery', 'queryLabel', 'searchPlaceholder', 'submit',
  'loading', 'error', 'unavailable', 'noResults', 'fallback', 'resultCount',
  'detailTitle', 'selectPlace', 'pinReady', 'pinUnavailable', 'mapsLink',
  'rating', 'reviews', 'openNow', 'closedNow', 'openUnknown', 'businessStatus',
  'type', 'accessibility', 'address', 'coordinates', 'unknown', 'responseNote',
];

function read(filePath) {
  return readFileSync(filePath, 'utf8');
}

function walkFiles(dir, files = []) {
  for (const entry of readdirSync(dir)) {
    if (['.next', 'node_modules'].includes(entry)) continue;
    const fullPath = path.join(dir, entry);
    const stat = statSync(fullPath);
    if (stat.isDirectory()) {
      walkFiles(fullPath, files);
    } else if (/\.(?:ts|tsx|js|jsx|mjs|json)$/.test(entry)) {
      files.push(fullPath);
    }
  }
  return files;
}

function relative(filePath) {
  return path.relative(frontendDir, filePath);
}

test('/map route renders PlaceProofMap instead of placeholder', () => {
  const page = read(pagePath);
  assert.match(page, /import\s+\{\s*PlaceProofMap\s*\}\s+from ['"]@\/components\/map\/place-proof-map['"]/);
  assert.match(page, /<PlaceProofMap\b/);
  assert.doesNotMatch(page, /PlaceholderPage/);
  assert.match(page, /setRequestLocale\(locale\)/);
  assert.match(page, /notFound\(\)/);
});

test('PlaceProofMap delegates recommendation intelligence only to /api/chat client seam', () => {
  const source = read(componentPath);
  const chatApi = read(chatApiPath);
  const apiRoute = read(apiRoutePath);

  assert.match(source, /import\s+\{[^}]*\bsendChat\b/);
  assert.match(source, /sendChat\(/);
  assert.match(chatApi, /fetch\(['"]\/api\/chat['"]/);
  assert.match(apiRoute, /BACKEND_URL/);
});

test('PlaceProofMap exposes failure, empty, fallback, pin, detail, and Maps-link states', () => {
  const source = read(componentPath);
  for (const token of [
    'translations.unavailable',
    'translations.noResults',
    'translations.fallback',
    'translations.pinUnavailable',
    'google_maps_uri',
    'target="_blank"',
    'rel="noreferrer"',
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

test('frontend source and tests do not own browser-side Google Places lookup', () => {
  const forbiddenPatterns = [
    /places\.googleapis\.com/i,
    /google\.maps\.places/i,
    /\bPlacesService\b/,
    /\bGooglePlacesService\b/,
    /\bNEXT_PUBLIC_GOOGLE_PLACES\b/,
  ];
  const scannedRoots = [path.join(frontendDir, 'src'), path.join(frontendDir, 'tests')];
  const violations = [];

  for (const filePath of scannedRoots.flatMap((root) => walkFiles(root))) {
    const text = read(filePath);
    if (filePath === import.meta.filename) continue;
    for (const pattern of forbiddenPatterns) {
      if (pattern.test(text)) violations.push(`${relative(filePath)} contains ${pattern}`);
    }
  }

  assert.deepEqual(violations, [], `browser-side Places ownership strings are forbidden:\n${violations.join('\n')}`);
});

test('Map message catalogs include matching non-empty proof-surface keys', () => {
  const catalogs = {
    en: JSON.parse(read(enMessagesPath)).Map,
    vi: JSON.parse(read(viMessagesPath)).Map,
  };

  for (const [locale, mapMessages] of Object.entries(catalogs)) {
    assert.ok(mapMessages, `${locale} catalog must include Map messages`);
    assert.deepEqual(Object.keys(mapMessages).sort(), [...requiredMapKeys].sort(), `${locale} Map keys must match the S03 contract`);
    for (const key of requiredMapKeys) {
      assert.equal(typeof mapMessages[key], 'string', `${locale} Map.${key} must be a string`);
      assert.ok(mapMessages[key].trim().length > 0, `${locale} Map.${key} must not be empty`);
    }
  }
});

console.log('S03 Map proof contract test loaded — verifies localized backend-only place proof surface');
