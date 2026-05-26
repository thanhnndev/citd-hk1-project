/**
 * S07 T01: Browser E2E coverage for full auth lifecycle.
 *
 * Flow: register → verify email (mocked SMTP) → login → access protected admin dashboard.
 * All API calls mocked at the Playwright network layer.
 *
 * Runs: cd frontend && node tests/s07-auth-e2e.test.mjs
 */

import { chromium } from '@playwright/test';
import assert from 'node:assert/strict';

const BASE_URL = process.env.FRONTEND_URL ?? 'http://localhost:3000';

// Synthetic JWT — opaque string that the frontend stores in localStorage.
// Header: {"alg":"HS256","typ":"JWT"}
// Payload: {"sub":"test-user-id","email":"test@example.com","exp":1999999999}
const SYNTHETIC_JWT =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9' +
  '.eyJzdWIiOiJ0ZXN0LXVzZXItaWQiLCJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJleHAiOjE5OTk5OTk5OTl9' +
  '.fake-signature';

async function installAuthMocks(page, seenRequests) {
  // POST /api/auth/register
  await page.route('**/api/auth/register', async (route) => {
    const body = JSON.parse(route.request().postData() ?? '{}');
    seenRequests.push({ kind: 'register', username: body.username, email: body.email });
    return route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'test-user-id',
        username: body.username,
        email: body.email,
        is_active: true,
        is_verified: false,
        created_at: '2026-05-24T00:00:00Z',
      }),
    });
  });

  // POST /api/auth/verify-email
  await page.route('**/api/auth/verify-email', async (route) => {
    const body = JSON.parse(route.request().postData() ?? '{}');
    seenRequests.push({ kind: 'verify-email', email: body.email, otp: body.otp });
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        message: 'Email verified successfully.',
        verified: true,
      }),
    });
  });

  // POST /api/auth/login
  await page.route('**/api/auth/login', async (route) => {
    const body = JSON.parse(route.request().postData() ?? '{}');
    seenRequests.push({ kind: 'login', email: body.email });
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        access_token: SYNTHETIC_JWT,
        token_type: 'bearer',
      }),
    });
  });

  // GET /api/auth/me — called by login-form.tsx after login success
  await page.route('**/api/auth/me', async (route) => {
    seenRequests.push({ kind: 'me' });
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'test-user-id',
        username: 'testuser',
        email: 'test@example.com',
        is_active: true,
        is_verified: true,
        created_at: '2026-05-24T00:00:00Z',
      }),
    });
  });

  // GET /api/admin/stats
  await page.route('**/api/admin/stats', async (route) => {
    seenRequests.push({ kind: 'admin-stats' });
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total_docs: 42,
        total_chunks: 312,
        language_distribution: { vi: 21, en: 21 },
        bm25_vocab_size: 1500,
        hybrid_enabled: true,
        qdrant_collection_name: 'ham_ninh_chunks',
      }),
    });
  });

  // GET /api/admin/traces
  await page.route('**/api/admin/traces', async (route) => {
    seenRequests.push({ kind: 'admin-traces' });
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        langfuse_enabled: true,
        host: 'https://cloud.langfuse.com',
        message: 'Langfuse tracing active',
      }),
    });
  });

  // GET /api/admin/fairness
  await page.route('**/api/admin/fairness', async (route) => {
    seenRequests.push({ kind: 'admin-fairness' });
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total_audits: 10,
        latest_timestamp: '2026-05-24T00:00:00Z',
        local_factor_distribution: { mean: 0.85 },
        message: 'Fairness audit data available',
      }),
    });
  });
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
    await installAuthMocks(page, seenRequests);

    // ── Step 1: Register ──────────────────────────────────────────
    await page.goto(`${BASE_URL}/vi/auth/register`, { waitUntil: 'networkidle', timeout: 15000 });

    await page.locator('#username').fill('testuser');
    await page.locator('#email').fill('test@example.com');
    await page.locator('#password').fill('TestPass123');
    await page.getByRole('button', { name: 'Tạo tài khoản' }).click();

    // Wait for success message (form shows verifyPrompt text)
    await page.getByText('Tài khoản đã được tạo!').waitFor({ timeout: 5000 });

    // Wait for redirect to verify-email page
    await page.waitForURL(/\/vi\/auth\/verify-email.*email=test/, { timeout: 10000 });
    assert.ok(
      page.url().includes('email=test%40example.com') || page.url().includes('email=test@example.com'),
      `Verify page URL should contain email param, got: ${page.url()}`,
    );

    // ── Step 2: Verify Email ──────────────────────────────────────
    // OTP input has opacity-0 styling but is still interactable via aria-label
    const otpInput = page.getByLabel('Mã OTP');
    await otpInput.waitFor({ timeout: 5000 });
    await otpInput.fill('123456');
    await page.getByRole('button', { name: 'Xác thực' }).click();

    // Wait for success message
    await page.getByText('Email đã được xác thực thành công!').waitFor({ timeout: 5000 });

    // Wait for redirect to login page
    await page.waitForURL(/\/vi\/auth\/login/, { timeout: 10000 });
    assert.ok(page.url().includes('/vi/auth/login'), `Should redirect to login page, got: ${page.url()}`);

    // ── Step 3: Login ─────────────────────────────────────────────
    await page.locator('#email').fill('test@example.com');
    await page.locator('#password').fill('TestPass123');
    await page.getByRole('button', { name: 'Đăng nhập' }).click();

    // Wait for redirect to chat (login-form pushes to /vi/chat after /api/auth/me)
    await page.waitForURL(/\/vi\/chat/, { timeout: 15000 });
    assert.ok(page.url().includes('/vi/chat'), `Should redirect to chat page, got: ${page.url()}`);

    // Verify token persisted in localStorage
    const token = await page.evaluate(() => localStorage.getItem('ham_ninh_token'));
    assert.ok(token && token.length > 0, 'ham_ninh_token should be a non-empty string in localStorage');
    assert.equal(token, SYNTHETIC_JWT, 'Token should match the synthetic JWT');

    // ── Step 4: Admin Dashboard ───────────────────────────────────
    await page.goto(`${BASE_URL}/vi/admin`, { waitUntil: 'networkidle', timeout: 15000 });

    // Wait for dashboard title (AdminLoginGate passes through since token exists)
    await page.getByText('Bảng quản trị').waitFor({ timeout: 10000 });

    // Verify all four stat card section titles are visible
    await page.getByText('Kho dữ liệu').waitFor({ timeout: 5000 });
    await page.getByText('Đánh giá RAGAS').waitFor({ timeout: 5000 });
    await page.getByText('Langfuse Traces').waitFor({ timeout: 5000 });
    await page.getByText('Kiểm tra công bằng').waitFor({ timeout: 5000 });

    // Verify specific mocked data values rendered
    await page.getByText('42').waitFor({ timeout: 5000 });
    await page.getByText('312 chunks').waitFor({ timeout: 5000 });
    await page.getByText('10').waitFor({ timeout: 5000 });

    // ── Verify network requests ───────────────────────────────────
    const registerReq = seenRequests.find((r) => r.kind === 'register');
    assert.ok(registerReq, 'Should have made a register request');
    assert.equal(registerReq.username, 'testuser');
    assert.equal(registerReq.email, 'test@example.com');

    const verifyReq = seenRequests.find((r) => r.kind === 'verify-email');
    assert.ok(verifyReq, 'Should have made a verify-email request');
    assert.equal(verifyReq.otp, '123456');

    const loginReq = seenRequests.find((r) => r.kind === 'login');
    assert.ok(loginReq, 'Should have made a login request');
    assert.equal(loginReq.email, 'test@example.com');

    const meReq = seenRequests.find((r) => r.kind === 'me');
    assert.ok(meReq, 'Should have made a /api/auth/me request after login');

    const adminStatsReq = seenRequests.find((r) => r.kind === 'admin-stats');
    assert.ok(adminStatsReq, 'Should have made an admin-stats request');

    const adminTracesReq = seenRequests.find((r) => r.kind === 'admin-traces');
    assert.ok(adminTracesReq, 'Should have made an admin-traces request');

    const adminFairnessReq = seenRequests.find((r) => r.kind === 'admin-fairness');
    assert.ok(adminFairnessReq, 'Should have made an admin-fairness request');

    // ── Verify no unexpected console errors ───────────────────────
    assert.deepEqual(consoleErrors, [], `No unexpected console errors: ${consoleErrors.join('; ')}`);

    console.log(
      'S07 auth E2E passed: register → verify → login → admin dashboard verified. ' +
      `${seenRequests.length} API calls mocked and captured.`,
    );
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
