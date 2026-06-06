import assert from 'node:assert/strict';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';

const frontendDir = path.resolve(import.meta.dirname, '..');
const repoRoot = path.resolve(frontendDir, '..');
const packagePath = path.join(frontendDir, 'package.json');
const envExamplePath = path.join(repoRoot, '.env.example');
const goongComponentPath = path.join(frontendDir, 'src/components/map/goong-place-map.tsx');
const legacyProofComponentPath = path.join(frontendDir, 'src/components/map/place-proof-map.tsx');
const chatApiPath = path.join(frontendDir, 'src/lib/chat-api.ts');
const apiRoutePath = path.join(frontendDir, 'src/app/api/chat/route.ts');
const enMessagesPath = path.join(frontendDir, 'messages/en.json');
const viMessagesPath = path.join(frontendDir, 'messages/vi.json');

const requiredMapKeys = [
  'title', 'intro', 'defaultQuery', 'queryLabel', 'searchPlaceholder', 'submit',
  'loading', 'error', 'unavailable', 'noResults', 'fallback', 'resultCount',
  'detailTitle', 'selectPlace', 'pinReady', 'pinUnavailable', 'missingMapToken',
  'mapUnavailable', 'noPins', 'mapsLink',
  'rating', 'reviews', 'openNow', 'closedNow', 'openUnknown', 'businessStatus',
  'type', 'accessibility', 'address', 'coordinates', 'unknown', 'responseNote',
];

function read(filePath) {
  return readFileSync(filePath, 'utf8');
}

function readIfExists(filePath) {
  return existsSync(filePath) ? read(filePath) : '';
}

function walkFiles(dir, files = []) {
  if (!existsSync(dir)) return files;
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

test('frontend declares the browser map renderer dependency', () => {
  const pkg = JSON.parse(read(packagePath));
  assert.equal(typeof pkg.dependencies?.['mapbox-gl'], 'string', 'mapbox-gl must be a runtime dependency for the client map');
});

test('.env.example exposes only the browser-safe Goong map tiles token', () => {
  const envExample = read(envExamplePath);
  assert.match(envExample, /^NEXT_PUBLIC_GOONG_MAPTILES_KEY=/m);
  const legacyProvider = ['GOO', 'GLE'].join('');
  assert.doesNotMatch(envExample, new RegExp(`^NEXT_PUBLIC_${legacyProvider}_MAPS_JS_API_KEY=`, 'm'));
  assert.doesNotMatch(envExample, new RegExp(`^${legacyProvider}_MAPS_JS_API_KEY=`, 'm'));
  const serverGoongKey = ['GOONG', 'API', 'KEY'].join('_');
  assert.match(envExample, new RegExp(`^${serverGoongKey}=`, 'm'), 'server Goong key remains documented for backend-owned place intelligence');
});

test('GoongPlaceMap component owns Goong Mapbox GL initialization and token fallbacks', () => {
  assert.ok(existsSync(goongComponentPath), 'src/components/map/goong-place-map.tsx must define the real Goong map renderer');
  const source = readIfExists(goongComponentPath);

  assert.match(source, /import\s+mapboxgl\s+from ['"]mapbox-gl['"]/);
  assert.match(source, /new\s+mapboxgl\.Map\s*\(/);
  assert.match(source, /process\.env\.NEXT_PUBLIC_GOONG_MAPTILES_KEY/);
  assert.match(source, /tiles\.goong\.io/);
  assert.match(source, /style\.json\?api_key=|api_key=\$\{/);
  assert.match(source, /HAM_NINH_CENTER[^\n]*104\.0496843[^\n]*10\.1835208/);
  assert.match(source, /mapboxgl\.accessToken\s*=.*HARMLESS_MAPBOX_TOKEN/);
  assert.doesNotMatch(source, new RegExp(`process\\.env\\.${['GOONG', 'API', 'KEY'].join('_')}`));
  assert.doesNotMatch(source, /fetch\s*\(/);
  assert.match(source, /missing(?:Map)?Token|missing-token|NEXT_PUBLIC_GOONG_MAPTILES_KEY/i);
  assert.match(source, /unavailableLabel/);
  assert.match(source, /emptyLabel/);
  assert.match(source, /onMarkerSelect/);
  assert.match(source, /selectedPlaceId/);
});

test('PlaceProofMap keeps recommendation intelligence on sendChat and delegates rendering to GoongPlaceMap', () => {
  const source = read(legacyProofComponentPath);
  const chatApi = read(chatApiPath);
  const apiRoute = read(apiRoutePath);

  assert.match(source, /import\s+\{\s*GoongPlaceMap\s*\}\s+from ['"]@\/components\/map\/goong-place-map['"]/);
  assert.match(source, /<GoongPlaceMap\b/);
  assert.match(source, /missingTokenLabel=\{translations\.missingMapToken\}/);
  assert.match(source, /unavailableLabel=\{translations\.mapUnavailable\}/);
  assert.match(source, /emptyLabel=\{translations\.noPins\}/);
  assert.doesNotMatch(source, /staticPlotPosition/);
  assert.match(source, /import\s+\{[^}]*\bsendChat\b/);
  assert.match(source, /sendChat\(/);
  assert.match(chatApi, /fetch\(['"]\/api\/chat['"]/);
  assert.match(apiRoute, /BACKEND_URL/);
});

test('frontend source, tests, and messages reject legacy map provider contracts', () => {
  const legacyProvider = ['goo', 'gle'].join('');
  const forbiddenPatterns = [
    new RegExp(`\\b${legacyProvider}_maps_uri\\b`, 'i'),
    new RegExp(`places\\.${legacyProvider}apis\\.com`, 'i'),
    new RegExp(`maps\\.${legacyProvider}apis\\.com`, 'i'),
    new RegExp(`${legacyProvider}\\.maps\\.places`, 'i'),
    new RegExp(`${legacyProvider}\\.maps\\.Map`, 'i'),
    /\bPlacesService\b/,
    new RegExp(`\\b${legacyProvider}PlacesService\\b`, 'i'),
    new RegExp(`\\bNEXT_PUBLIC_${legacyProvider.toUpperCase()}_(?:MAPS|PLACES)`, 'i'),
    new RegExp(`\\b${legacyProvider.toUpperCase()}_MAPS_JS_API_KEY\\b`, 'i'),
    new RegExp(`\\b${['GOONG', 'API', 'KEY'].join('_')}\\b`),
    new RegExp(`${legacyProvider}\\s+Maps`, 'i'),
    new RegExp(`${legacyProvider}\\s+Maps\\s+Platform`, 'i'),
  ];
  const scannedRoots = [path.join(frontendDir, 'src'), path.join(frontendDir, 'tests'), path.join(frontendDir, 'messages')];
  const violations = [];

  for (const filePath of scannedRoots.flatMap((root) => walkFiles(root))) {
    if (filePath === import.meta.filename) continue;
    const text = read(filePath);
    for (const pattern of forbiddenPatterns) {
      if (pattern.test(text)) violations.push(`${relative(filePath)} contains ${pattern}`);
    }
  }

  assert.deepEqual(violations, [], `legacy Google provider strings are forbidden in frontend contracts:\n${violations.join('\n')}`);
});

test('Map message catalogs include matching non-empty proof-surface keys', () => {
  const catalogs = {
    en: JSON.parse(read(enMessagesPath)).Map,
    vi: JSON.parse(read(viMessagesPath)).Map,
  };

  for (const [locale, mapMessages] of Object.entries(catalogs)) {
    assert.ok(mapMessages, `${locale} catalog must include Map messages`);
    assert.deepEqual(Object.keys(mapMessages).sort(), [...requiredMapKeys].sort(), `${locale} Map keys must match the S03 contract`);
    const legacyProvider = ['goo', 'gle'].join('');
    const legacyMapBrand = new RegExp(`${legacyProvider}\\s+Maps|${legacyProvider}\\s+Maps\\s+SDK`, 'i');
    assert.doesNotMatch(mapMessages.intro + mapMessages.mapsLink, legacyMapBrand, `${locale} Map copy should not brand the neutral source link as legacy-provider UI`);
    for (const key of requiredMapKeys) {
      assert.equal(typeof mapMessages[key], 'string', `${locale} Map.${key} must be a string`);
      assert.ok(mapMessages[key].trim().length > 0, `${locale} Map.${key} must not be empty`);
    }
  }
});

console.log('S03 Goong map contract test loaded - verifies public map tiles boundary and backend-owned place intelligence');
