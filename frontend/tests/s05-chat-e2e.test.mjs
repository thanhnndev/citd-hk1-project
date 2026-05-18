/**
 * S05 T03: Browser E2E coverage for multi-turn streaming chat.
 *
 * Runs: cd frontend && node tests/s05-chat-e2e.test.mjs
 */

import { chromium } from '@playwright/test';
import assert from 'node:assert/strict';

const BASE_URL = process.env.FRONTEND_URL ?? 'http://localhost:3000';
const CHAT_URL = `${BASE_URL}/vi/chat`;

const FIRST_QUESTION = 'Hàm Ninh có nét văn hóa nào nổi bật?';
const FOLLOW_UP = 'Vậy món ăn nào liên quan đến nơi đó?';
const UNKNOWN_QUESTION = 'Có lễ hội Atlantis nào ở Hàm Ninh không?';
const STREAM_ERROR_QUESTION = 'Hãy gửi citations lỗi';

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

    return route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ error: `Unexpected message: ${message}` }),
    });
  });

  await page.route('**/api/chat', async (route) => {
    const body = JSON.parse(route.request().postData() ?? '{}');
    seenRequests.push({ ...body, kind: 'post' });
    return route.fulfill({ ...postFallbackFulfill(body.session_id) });
  });
}

async function submitQuestion(page, question) {
  const input = page.getByRole('textbox', { name: 'Nhập câu hỏi về Hàm Ninh...' });
  await input.fill(question);
  await page.getByRole('button', { name: 'Gửi' }).click();
}

async function main() {
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

    const streamRequests = seenRequests.filter((request) => request.kind === 'stream');
    assert.equal(streamRequests.length, 4, 'Expected four stream requests');
    assert.ok(streamRequests.every((request) => request.language === 'vi'), 'All stream requests should use Vietnamese language');
    const sessionIds = new Set(streamRequests.map((request) => request.sessionId));
    assert.equal(sessionIds.size, 1, 'Follow-up and negative turns should reuse the same generated session_id');
    assert.match([...sessionIds][0], /^[0-9a-f-]{36}$/i, 'Session id should look like a UUID');

    const postFallback = seenRequests.find((request) => request.kind === 'post');
    assert.ok(postFallback, 'Malformed citations should trigger POST fallback instead of silent success');
    assert.equal(postFallback.session_id, streamRequests[0].sessionId, 'POST fallback should keep the same session_id');

    assert.deepEqual(consoleErrors, [], `No browser console errors expected: ${consoleErrors.join('; ')}`);
    console.log('S05 chat E2E passed: streaming, citations, same-session follow-up, no-evidence, and fallback verified.');
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
