/**
 * S06 T02: Credential-aware browser verifier for Goong tiles and map pins.
 *
 * Runs: cd frontend && node --test tests/s06-goong-map-live.test.mjs
 */

import { chromium } from '@playwright/test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { test } from 'node:test';

const BASE_URL = process.env.FRONTEND_URL ?? process.env.BASE_URL ?? 'http://localhost:3000';
const MAP_URL = `${BASE_URL}/vi/map`;
const PUBLIC_TILE_KEY = process.env.NEXT_PUBLIC_GOONG_MAPTILES_KEY ?? '';
const PLACE_QUERY = 'Nhà hàng hải sản có tọa độ ở Hàm Ninh';

const PLACE_FIXTURES = [
  {
    place_id: 's06-ham-ninh-001',
    display_name: 'S06 Hải sản Hàm Ninh Pier',
    formatted_address: 'Bến Hàm Ninh, Phú Quốc, Kiên Giang',
    location: { lat: 10.18485, lng: 104.0512 },
    types: ['restaurant', 'seafood_restaurant', 'point_of_interest'],
    primary_type: 'seafood_restaurant',
    rating: 4.6,
    user_rating_count: 321,
    price_level: 2,
    open_now: true,
    business_status: 'OPERATIONAL',
    local_factor: 0.94,
    final_score: 0.91,
    score_breakdown: {
      tree1_locality: 0.96,
      tree2_proximity: 0.92,
      tree3_quality: 0.88,
      s_bag: 0.84,
      delta1_fairness: 0.9,
      delta2_access: 0.87,
      final_score: 0.91,
      rank: 1,
    },
    accessibility_score: 0.72,
    map_uri: 'https://map.goong.io/place/s06-ham-ninh-001',
  },
  {
    place_id: 's06-ham-ninh-002',
    display_name: 'S06 Quán ghẹ Làng Chài',
    formatted_address: 'Làng chài Hàm Ninh, Phú Quốc',
    location: { lat: 10.18195, lng: 104.04791 },
    types: ['restaurant', 'food'],
    primary_type: 'restaurant',
    rating: 4.4,
    user_rating_count: 198,
    price_level: 2,
    open_now: true,
    business_status: 'OPERATIONAL',
    local_factor: 0.9,
    final_score: 0.86,
    score_breakdown: {
      tree1_locality: 0.91,
      tree2_proximity: 0.87,
      tree3_quality: 0.83,
      s_bag: 0.79,
      delta1_fairness: 0.82,
      delta2_access: 0.8,
      final_score: 0.86,
      rank: 2,
    },
    accessibility_score: 0.68,
    map_uri: 'https://map.goong.io/place/s06-ham-ninh-002',
  },
  {
    place_id: 's06-no-coordinate-control',
    display_name: 'S06 Control Without Coordinates',
    formatted_address: 'Hàm Ninh, Phú Quốc',
    location: null,
    types: ['restaurant'],
    primary_type: 'restaurant',
    rating: 4.0,
    user_rating_count: 12,
    price_level: 1,
    open_now: null,
    business_status: 'OPERATIONAL',
    local_factor: 0.5,
    final_score: 0.4,
    score_breakdown: {
      tree1_locality: 0.5,
      tree2_proximity: 0.4,
      tree3_quality: 0.4,
      s_bag: 0.3,
      delta1_fairness: 0.5,
      delta2_access: 0.3,
      final_score: 0.4,
      rank: 3,
    },
    map_uri: 'https://map.goong.io/place/s06-no-coordinate-control',
  },
];

function sanitize(value) {
  if (!PUBLIC_TILE_KEY) return value;
  return String(value).split(PUBLIC_TILE_KEY).join('[redacted-goong-tiles-key]');
}

function isPlaceholderKey(value) {
  const normalized = value.trim().toLowerCase();
  if (!normalized) return true;
  return [
    'changeme',
    'change_me',
    'placeholder',
    'your_goong_maptiles_key',
    'your-goong-maptiles-key',
    'goong_maptiles_key',
    'goong-public-tiles',
    'test',
    'fake',
    'dummy',
  ].some((token) => normalized === token || normalized.includes(token));
}

function emitResult(result, details = {}) {
  console.log(`RESULT=${result} ${JSON.stringify(details, (_key, value) => (typeof value === 'string' ? sanitize(value) : value))}`);
}

async function isServerReady() {
  try {
    const response = await fetch(BASE_URL, { signal: AbortSignal.timeout(1000) });
    return response.status < 500;
  } catch {
    return false;
  }
}

async function startFrontendServerIfNeeded() {
  if (process.env.FRONTEND_URL || process.env.BASE_URL || (await isServerReady())) return undefined;

  const child = spawn('bun', ['run', 'dev'], {
    cwd: process.cwd(),
    env: { ...process.env, NEXT_TELEMETRY_DISABLED: '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  const logs = [];
  child.stdout.on('data', (chunk) => logs.push(chunk.toString()));
  child.stderr.on('data', (chunk) => logs.push(chunk.toString()));

  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    if (await isServerReady()) return child;
    if (child.exitCode !== null) break;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }

  child.kill('SIGTERM');
  throw new Error(`Timed out waiting for frontend dev server at ${BASE_URL}. Logs:\n${sanitize(logs.join('').slice(-4000))}`);
}

async function stopFrontendServer(child) {
  if (!child || child.exitCode !== null) return;
  child.kill('SIGTERM');
  await new Promise((resolve) => {
    const timer = setTimeout(resolve, 5000);
    child.once('exit', () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

async function installChatMock(page, seenRequests) {
  await page.route('**/api/chat', async (route) => {
    const body = JSON.parse(route.request().postData() ?? '{}');
    seenRequests.push({ message: body.message, language: body.language, sessionId: body.session_id });
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session_id: body.session_id,
        message: 'S06 mocked coordinate-bearing Goong place results for Hàm Ninh.',
        citations: [],
        places: PLACE_FIXTURES,
        latency_ms: 42,
      }),
    });
  });
}

test('S06 Goong live map verifier observes tiles, pins, and marker selection', async () => {
  if (isPlaceholderKey(PUBLIC_TILE_KEY)) {
    emitResult('credential_blocked', { reason: 'missing_or_placeholder_NEXT_PUBLIC_GOONG_MAPTILES_KEY' });
    return;
  }

  const diagnostics = {
    baseUrl: BASE_URL,
    goongUrls: [],
    failedGoong: [],
    consoleErrors: [],
    pageErrors: [],
    chatRequests: [],
  };
  let server;
  let browser;

  try {
    server = await startFrontendServerIfNeeded();
    browser = await chromium.launch({ args: ['--no-sandbox'] });
    const context = await browser.newContext({ viewport: { width: 1280, height: 850 } });
    const page = await context.newPage();

    page.on('console', (msg) => {
      if (msg.type() === 'error') diagnostics.consoleErrors.push(sanitize(msg.text()));
    });
    page.on('pageerror', (err) => diagnostics.pageErrors.push(sanitize(`PageError: ${err.message}`)));
    page.on('request', (request) => {
      const url = request.url();
      if (isGoongUrl(url)) diagnostics.goongUrls.push(sanitize(url));
    });
    page.on('response', (response) => {
      const url = response.url();
      if (!isGoongUrl(url)) return;
      diagnostics.goongUrls.push(sanitize(url));
      if ([401, 403].includes(response.status()) || response.status() >= 500) {
        diagnostics.failedGoong.push({ status: response.status(), url: sanitize(url) });
      }
    });
    page.on('requestfailed', (request) => {
      const url = request.url();
      if (isGoongUrl(url)) diagnostics.failedGoong.push({ failure: request.failure()?.errorText ?? 'requestfailed', url: sanitize(url) });
    });

    await installChatMock(page, diagnostics.chatRequests);

    const response = await page.goto(MAP_URL, { waitUntil: 'domcontentloaded', timeout: 15000 });
    assert.ok(response, 'Vietnamese map route should respond');
    assert.ok(response.status() < 400, `Vietnamese map route status should be < 400, got ${response.status()}`);

    const input = page.getByRole('textbox', { name: /hỏi|query|search|tìm/i });
    await input.waitFor({ timeout: 10000 });
    await input.fill(PLACE_QUERY);
    await page.getByRole('button', { name: /gửi|send|search|tìm/i }).click();

    await page.getByText('S06 Hải sản Hàm Ninh Pier').waitFor({ timeout: 10000 });
    await page.getByText('S06 Quán ghẹ Làng Chài').waitFor({ timeout: 10000 });

    const markerOne = page.getByRole('button', { name: /Chọn địa điểm: S06 Hải sản Hàm Ninh Pier/ });
    const markerTwo = page.getByRole('button', { name: /Chọn địa điểm: S06 Quán ghẹ Làng Chài/ });
    await markerOne.waitFor({ timeout: 15000 });
    await markerTwo.waitFor({ timeout: 15000 });
    assert.equal(await page.getByRole('button', { name: /Chọn địa điểm: S06 Control Without Coordinates/ }).count(), 0, 'Coordinate-less control should not render a map marker');

    await markerTwo.click();
    await page.getByRole('heading', { name: /S06 Quán ghẹ Làng Chài/ }).waitFor({ timeout: 5000 });
    assert.ok(diagnostics.chatRequests.some((request) => request.message === PLACE_QUERY && request.language === 'vi'), 'Map flow should call the mocked /api/chat endpoint with vi language');

    await page.waitForTimeout(1500);
    assert.ok(diagnostics.goongUrls.some((url) => /tiles\.goong\.io|goong_map_web\.json/.test(url)), 'Expected Goong style or tile network activity');
    assert.deepEqual(diagnostics.failedGoong, [], `Goong network failures: ${JSON.stringify(diagnostics.failedGoong)}`);
    assert.deepEqual(diagnostics.pageErrors, [], `No page errors: ${diagnostics.pageErrors.join('; ')}`);
    assert.deepEqual(diagnostics.consoleErrors, [], `No console errors: ${diagnostics.consoleErrors.join('; ')}`);

    emitResult('passed', {
      baseUrl: BASE_URL,
      goongSignalCount: diagnostics.goongUrls.length,
      renderedMarkers: 2,
      selectedPlace: 's06-ham-ninh-002',
    });
    await context.close();
  } catch (error) {
    emitResult('failed', { error: error instanceof Error ? error.message : String(error), diagnostics });
    throw error;
  } finally {
    if (browser) await browser.close();
    await stopFrontendServer(server);
  }
});

function isGoongUrl(url) {
  return url.includes('tiles.goong.io') || url.includes('goong_map_web.json');
}
