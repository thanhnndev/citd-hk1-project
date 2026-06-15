/**
 * S05 T03: Browser E2E coverage for multi-turn streaming chat.
 *
 * Runs: cd frontend && node tests/s05-chat-e2e.test.mjs
 */

import { chromium } from '@playwright/test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';

const BASE_URL = process.env.FRONTEND_URL ?? 'http://localhost:3000';
const CHAT_URL = `${BASE_URL}/vi/chat`;

const FIRST_QUESTION = 'Hàm Ninh có nét văn hóa nào nổi bật?';
const FOLLOW_UP = 'Vậy món ăn nào liên quan đến nơi đó?';
const UNKNOWN_QUESTION = 'Có lễ hội Atlantis nào ở Hàm Ninh không?';
const STREAM_ERROR_QUESTION = 'Hãy gửi citations lỗi';
const PLACE_QUESTION = 'Nhà hàng hải sản ở Hàm Ninh';

function sseEvent(data) {
  return `data: ${data}\n\n`;
}

function sseFulfill(events) {
  return {
    status: 200,
    contentType: 'text/event-stream',
    headers: { 'Cache-Control': 'no-cache' },
    body: events.join(''),
  };
}

function postFallbackFulfill(sessionId) {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      session_id: sessionId,
      message: 'Luồng trả lời gặp lỗi nên vui lòng thử lại.',
      citations: [],
      places: [],
      latency_ms: 12,
    }),
  };
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
  if (process.env.FRONTEND_URL || (await isServerReady())) return undefined;

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
  throw new Error(`Timed out waiting for frontend dev server at ${BASE_URL}. Logs:\n${logs.join('').slice(-4000)}`);
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

async function installChatMocks(page, seenRequests) {
  await page.route('**/api/chat/stream**', async (route) => {
    const url = new URL(route.request().url());
    const message = url.searchParams.get('message') ?? '';
    const sessionId = url.searchParams.get('session_id') ?? '';
    const language = url.searchParams.get('language') ?? '';
    seenRequests.push({ message, sessionId, language, kind: 'stream' });

    if (message === FIRST_QUESTION) {
      return route.fulfill({
        ...sseFulfill([
          sseEvent('Hàm Ninh nổi bật với '),
          sseEvent('làng chài ven biển và tín ngưỡng miếu Bà.'),
          sseEvent(`[CITATIONS] ${JSON.stringify([
            {
              source: 'Sổ tay văn hóa Hàm Ninh',
              url: 'https://example.test/ham-ninh-culture',
              snippet: 'Làng chài Hàm Ninh gắn với sinh kế biển và không gian tín ngưỡng địa phương.',
            },
          ])}`),
          sseEvent('[DONE]'),
        ]),
      });
    }

    if (message === FOLLOW_UP) {
      return route.fulfill({
        ...sseFulfill([
          sseEvent('Dựa trên làng chài Hàm Ninh vừa nhắc, '),
          sseEvent('ghẹ Hàm Ninh là món tiêu biểu gắn với sinh kế biển.'),
          sseEvent(`[CITATIONS] ${JSON.stringify([
            {
              source: 'Ẩm thực địa phương Phú Quốc',
              url: 'https://example.test/ghe-ham-ninh',
              snippet: 'Ghẹ Hàm Ninh thường được giới thiệu như đặc sản gắn với làng chài.',
            },
          ])}`),
          sseEvent('[DONE]'),
        ]),
      });
    }

    if (message === UNKNOWN_QUESTION) {
      return route.fulfill({
        ...sseFulfill([
          sseEvent('Tôi chưa tìm thấy bằng chứng đáng tin cậy về lễ hội Atlantis ở Hàm Ninh.'),
          sseEvent('[DONE]'),
        ]),
      });
    }

    if (message === STREAM_ERROR_QUESTION) {
      return route.fulfill({
        ...sseFulfill([
          sseEvent('Một câu trả lời sẽ bị thay thế.'),
          sseEvent('[CITATIONS] {not-json'),
        ]),
      });
    }

    // Place intent: stream endpoint "doesn't emit places" — simulate failure to force POST fallback
    if (message === PLACE_QUESTION) {
      return route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Stream unavailable for place queries' }),
      });
    }

    return route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ error: `Unexpected message: ${message}` }),
    });
  });

  await page.route('**/api/chat', async (route) => {
    const body = JSON.parse(route.request().postData() ?? '{}');
    seenRequests.push({ ...body, kind: 'post' });

    // Place intent: return 2 re-ranked PlaceResult cards with full score_breakdown
    if (body.message === PLACE_QUESTION) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session_id: body.session_id,
          message: 'Dưới đây là một số nhà hàng hải sản gợi ý ở Hàm Ninh:',
          citations: [],
          places: [
            {
              place_id: 'ChIJplace001',
              display_name: 'Hải sản Hàm Ninh 1',
              formatted_address: 'Hàm Ninh, Phú Quốc, Kiên Giang',
              types: ['restaurant', 'food', 'point_of_interest'],
              primary_type: 'restaurant',
              rating: 4.3,
              user_rating_count: 1250,
              price_level: 2,
              open_now: true,
              business_status: 'OPERATIONAL',
              local_factor: 0.92,
              final_score: 0.87,
              score_breakdown: {
                relevance: 0.95,
                proximity: 0.88,
                quality: 0.85,
                geo_locality: 0.92,
                popularity_damping: 0.04,
                weights: { relevance: 0.4, proximity: 0.25, quality: 0.2, geo_locality: 0.15 },
                gate_passed: true,
                final_score: 0.87,
                rank: 1,
              },
              map_uri: 'https://map.goong.io/place/ChIJplace001',
            },
            {
              place_id: 'ChIJplace002',
              display_name: 'Nhà hàng Biển Xanh',
              formatted_address: 'Làng chài Hàm Ninh, Phú Quốc',
              types: ['restaurant', 'seafood_restaurant', 'food'],
              primary_type: 'restaurant',
              rating: 4.1,
              user_rating_count: 890,
              price_level: 2,
              open_now: true,
              business_status: 'OPERATIONAL',
              local_factor: 0.85,
              final_score: 0.79,
              score_breakdown: {
                relevance: 0.9,
                proximity: 0.82,
                quality: 0.78,
                geo_locality: 0.85,
                popularity_damping: 0.05,
                weights: { relevance: 0.4, proximity: 0.25, quality: 0.2, geo_locality: 0.15 },
                gate_passed: true,
                final_score: 0.79,
                rank: 2,
              },
              map_uri: 'https://map.goong.io/place/ChIJplace002',
            },
          ],
          latency_ms: 145,
        }),
      });
    }

    return route.fulfill({ ...postFallbackFulfill(body.session_id) });
  });
}

async function submitQuestion(page, question) {
  const input = page.getByRole('textbox', { name: 'Nhập câu hỏi về Hàm Ninh...' });
  await input.fill(question);
  await page.getByRole('button', { name: 'Gửi' }).click();
}

async function main() {
  const server = await startFrontendServerIfNeeded();
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  const consoleErrors = [];
  const seenRequests = [];

  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => consoleErrors.push(`PageError: ${err.message}`));

  try {
    await installChatMocks(page, seenRequests);
    const response = await page.goto(CHAT_URL, { waitUntil: 'networkidle', timeout: 15000 });
    assert.ok(response, 'Vietnamese chat route should respond');
    assert.ok(response.status() < 400, `Vietnamese chat route status should be < 400, got ${response.status()}`);
    await page.getByRole('textbox', { name: 'Nhập câu hỏi về Hàm Ninh...' }).waitFor({ timeout: 10000 });

    await submitQuestion(page, FIRST_QUESTION);
    await page.getByText('Hàm Ninh nổi bật với').waitFor({ timeout: 5000 });
    await page.getByText('làng chài ven biển và tín ngưỡng miếu Bà.').waitFor({ timeout: 5000 });
    await page.getByText('Sổ tay văn hóa Hàm Ninh').waitFor({ timeout: 5000 });
    await page.getByText('Làng chài Hàm Ninh gắn với sinh kế biển').waitFor({ timeout: 5000 });

    await submitQuestion(page, FOLLOW_UP);
    await page.getByText('Dựa trên làng chài Hàm Ninh vừa nhắc').waitFor({ timeout: 5000 });
    await page.getByText('ghẹ Hàm Ninh là món tiêu biểu').waitFor({ timeout: 5000 });
    await page.getByText('Ẩm thực địa phương Phú Quốc').waitFor({ timeout: 5000 });

    await submitQuestion(page, UNKNOWN_QUESTION);
    await page.getByText('Tôi chưa tìm thấy bằng chứng đáng tin cậy').waitFor({ timeout: 5000 });
    const atlantisCitationCount = await page.getByText('Atlantis', { exact: true }).count();
    assert.equal(atlantisCitationCount, 0, 'No fabricated Atlantis citation card should be rendered');

    await submitQuestion(page, STREAM_ERROR_QUESTION);
    await page.getByText('Luồng trả lời gặp lỗi nên vui lòng thử lại.').waitFor({ timeout: 5000 });

    // Place intent: stream fails → POST fallback → place cards render
    await submitQuestion(page, PLACE_QUESTION);
    await page.getByText('Dưới đây là một số nhà hàng hải sản gợi ý ở Hàm Ninh:').waitFor({ timeout: 5000 });
    await page.getByText('Hải sản Hàm Ninh 1').waitFor({ timeout: 5000 });
    await page.getByText('Nhà hàng Biển Xanh').waitFor({ timeout: 5000 });
    const placeCards = await page.getByRole('article').count();
    assert.ok(placeCards >= 2, `Expected at least 2 place cards, got ${placeCards}`);
    await page.getByText('0.87').waitFor({ timeout: 5000 });
    await page.getByText('0.79').waitFor({ timeout: 5000 });
    const mapLinks = await page.getByText('Xem trên Bản đồ').count();
    assert.ok(mapLinks >= 2, `Expected at least 2 'Xem trên Bản đồ' links, got ${mapLinks}`);

    const streamRequests = seenRequests.filter((request) => request.kind === 'stream');
    assert.equal(streamRequests.length, 5, 'Expected five stream requests (including place intent)');
    assert.ok(streamRequests.every((request) => request.language === 'vi'), 'All stream requests should use Vietnamese language');
    const sessionIds = new Set(streamRequests.map((request) => request.sessionId));
    assert.equal(sessionIds.size, 1, 'Follow-up and negative turns should reuse the same generated session_id');
    assert.match([...sessionIds][0], /^[0-9a-f-]{36}$/i, 'Session id should look like a UUID');

    const postFallback = seenRequests.find((request) => request.kind === 'post');
    assert.ok(postFallback, 'Malformed citations should trigger POST fallback instead of silent success');
    assert.equal(postFallback.session_id, streamRequests[0].sessionId, 'POST fallback should keep the same session_id');

    // Filter out expected 500 console errors from intentional stream failures (place intent, stream error)
    const unexpectedErrors = consoleErrors.filter((e) => !e.includes('500'));
    assert.deepEqual(unexpectedErrors, [], `No unexpected browser console errors: ${unexpectedErrors.join('; ')}`);
    console.log('S05 chat E2E passed: streaming, citations, same-session follow-up, no-evidence, fallback, and place card rendering verified.');
  } finally {
    await context.close();
    await browser.close();
    await stopFrontendServer(server);
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
