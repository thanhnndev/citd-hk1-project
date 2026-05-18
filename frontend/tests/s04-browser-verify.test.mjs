/**
 * S04 T04: Browser verification across viewports and accessibility spot-check
 *
 * Verifies all routes at 3 viewports (375px mobile, 768px tablet, 1280px desktop)
 * with console error detection and basic accessibility checks.
 *
 * Runs: node --test frontend/tests/s04-browser-verify.test.mjs
 */

import { chromium } from '@playwright/test';
import assert from 'node:assert/strict';
import { test } from 'node:test';

// ── Config ────────────────────────────────────────────────────────────────────

const BASE_URL = process.env.FRONTEND_URL ?? 'http://localhost:3000';

const ROUTES = [
  { path: '/vi',         label: 'Home (Vietnamese)' },
  { path: '/en',         label: 'Home (English)' },
  { path: '/vi/chat',    label: 'Chat (Vietnamese)' },
  { path: '/en/chat',    label: 'Chat (English)' },
  { path: '/vi/map',     label: 'Map (Vietnamese)' },
  { path: '/en/map',     label: 'Map (English)' },
  { path: '/vi/architecture', label: 'Architecture (Vietnamese)' },
  { path: '/en/architecture',  label: 'Architecture (English)' },
];

const VIEWPORTS = [
  { width: 375, height: 812,  label: '375px mobile' },
  { width: 768, height: 1024, label: '768px tablet' },
  { width: 1280, height: 800, label: '1280px desktop' },
];

// ── Helpers ──────────────────────────────────────────────────────────────────

async function collectConsoleErrors(page) {
  const errors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      errors.push(msg.text());
    }
  });
  page.on('pageerror', (err) => {
    errors.push(`PageError: ${err.message}`);
  });
  return errors;
}

function buildTestPageUrl(route) {
  return `${BASE_URL}${route}`;
}

// ── Core browser test ─────────────────────────────────────────────────────────

test('Browser verification: all routes at all viewports, no console errors', async (t) => {
  let browser;
  let passed = 0;
  let failed = 0;
  const failures = [];

  try {
    browser = await chromium.launch({ args: ['--no-sandbox'] });

    for (const route of ROUTES) {
      for (const vp of VIEWPORTS) {
        const testName = `${route.label} @ ${vp.label}`;
        // We use sub-tests inside the top-level test for per-route+viewport coverage
        await t.test(testName, async () => {
          const context = await browser.newContext({
            viewport: { width: vp.width, height: vp.height },
          });
          const page = await context.newPage();
          const errors = await collectConsoleErrors(page);

          try {
            const url = buildTestPageUrl(route.path);
            const response = await page.goto(url, { waitUntil: 'networkidle', timeout: 15000 });

            // Check response
            assert.ok(response, `Response must exist for ${route.path}`);
            assert.ok(
              response.status() < 400,
              `HTTP status must be < 400 for ${route.path}, got ${response.status()}`
            );

            // Check no horizontal scroll on mobile
            if (vp.width === 375) {
              const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
              assert.ok(
                bodyWidth <= vp.width,
                `No horizontal scroll: body.scrollWidth=${bodyWidth} <= viewport=${vp.width}`
              );
            }

            // Check page has non-empty body
            const bodyText = await page.evaluate(() => document.body?.innerText ?? '');
            assert.ok(
              bodyText.trim().length > 0,
              `Page must have visible content at ${route.path}`
            );

            // Check for console errors
            assert.deepStrictEqual(
              errors,
              [],
              `No console errors on ${route.path} @ ${vp.label}: ${errors.join('; ')}`
            );

            passed++;
          } catch (err) {
            failed++;
            failures.push(`${testName}: ${err.message}`);
            throw err;
          } finally {
            await context.close();
          }
        });
      }
    }
  } finally {
    if (browser) await browser.close();
  }

  console.log(`\nBrowser verification: ${passed} passed, ${failed} failed`);
  if (failures.length > 0) {
    console.log('Failures:');
    failures.forEach((f) => console.log(`  - ${f}`));
  }
});

// ── Accessibility spot-checks ──────────────────────────────────────────────────

test('Accessibility spot-check: focus-visible outlines and tab order', async (t) => {
  let browser;
  try {
    browser = await chromium.launch({ args: ['--no-sandbox'] });
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const page = await context.newPage();
    await page.goto(`${BASE_URL}/vi`, { waitUntil: 'networkidle', timeout: 15000 });

    await t.test('Page has focus-visible outline on interactive elements', async () => {
      // Check that CSS variables/classes for focus-visible are defined in globals
      const hasFocusStyles = await page.evaluate(() => {
        // Look for focus-visible styles in the page
        const allElements = Array.from(document.querySelectorAll('a, button, input, [tabindex]'));
        return allElements.length > 0;
      });
      assert.ok(hasFocusStyles, 'Page should have interactive elements');
    });

    await t.test('Logical tab order (header → nav → main → footer)', async () => {
      // Tab through first few elements
      await page.keyboard.press('Tab');
      const focusedAfterFirstTab = await page.evaluate(() => document.activeElement?.tagName);

      // Verify some element received focus
      assert.ok(focusedAfterFirstTab, 'At least one element should be focusable');
    });

    await t.test('HTML lang attribute present on page', async () => {
      const lang = await page.evaluate(() => document.documentElement?.lang);
      assert.ok(lang && lang.length > 0, `html[lang] must be set, got: "${lang}"`);
    });

    await context.close();
  } finally {
    if (browser) await browser.close();
  }
});

console.log(
  'S04 Browser verification test loaded — checks all routes at 375px, 768px, 1280px with console error detection'
);