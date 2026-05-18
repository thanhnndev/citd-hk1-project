/**
 * S04 T01: Browser chat submission test — verify end-to-end cited answer flow
 *
 * Tests the full vertical path: browser → Next.js proxy → FastAPI backend →
 * corpus retrieval → grounded cited answer rendered in the UI.
 *
 * Verifies both /vi/chat (Vietnamese) and /en/chat (English) locales.
 *
 * Runs: node --test frontend/tests/s04-chat-submit.test.mjs
 *
 * Requires: frontend dev server on FRONTEND_URL (default http://localhost:3000)
 *           backend dev server on port 48721 (proxy default)
 */

import { chromium } from '@playwright/test';
import assert from 'node:assert/strict';
import { test } from 'node:test';

// ── Config ────────────────────────────────────────────────────────────────────

const BASE_URL = process.env.FRONTEND_URL ?? 'http://localhost:3000';

// Test queries — culturally specific Hàm Ninh queries the corpus should recognize
const TEST_CASES = [
  {
    locale: 'vi',
    path: '/vi/chat',
    query: 'làng chài Hàm Ninh',
    label: 'Vietnamese chat: làng chài Hàm Ninh',
  },
  {
    locale: 'en',
    path: '/en/chat',
    query: 'Ham Ninh fishing village culture',
    label: 'English chat: Ham Ninh fishing village',
  },
];

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Collect console errors and page errors from a Playwright page.
 * Returns the array (mutated by event listeners).
 */
function collectConsoleErrors(page) {
  const errors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      errors.push(`[console] ${msg.text()}`);
    }
  });
  page.on('pageerror', (err) => {
    errors.push(`[pageerror] ${err.message}`);
  });
  return errors;
}

/**
 * Wait for the chat response to appear after submission.
 * Strategy: wait for loading spinner to appear, then disappear,
 * then verify assistant message content is present.
 */
async function waitForChatResponse(page, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;

  // Phase 1: Wait for loading indicator to appear (button spinner or typing dots)
  // The send button shows Loader2 (animate-spin) during loading
  try {
    await page.waitForSelector('.animate-spin', { state: 'visible', timeout: 5000 });
  } catch {
    // Loading may have been too fast — that's OK, proceed to check for response
  }

  // Phase 2: Wait for loading to finish (spinner disappears)
  // Poll for the spinner to be gone OR for assistant content to appear
  while (Date.now() < deadline) {
    const loadingGone = await page.evaluate(() => {
      const spinners = document.querySelectorAll('.animate-spin');
      return spinners.length === 0;
    });

    if (loadingGone) {
      // Check if there's assistant content
      const hasAssistantContent = await page.evaluate(() => {
        // Assistant messages are in bg-muted divs (not the user's bg-primary)
        const assistantBubbles = document.querySelectorAll('[role="log"] .bg-muted');
        for (const bubble of assistantBubbles) {
          const text = bubble.innerText?.trim();
          if (text && text.length > 0) {
            return true;
          }
        }
        return false;
      });

      if (hasAssistantContent) {
        return true;
      }
    }

    await new Promise((r) => setTimeout(r, 500));
  }

  // Timeout — check one more time what state we're in
  const finalState = await page.evaluate(() => {
    const spinners = document.querySelectorAll('.animate-spin').length;
    const assistantBubbles = document.querySelectorAll('[role="log"] .bg-muted');
    const bubbles = [];
    for (const b of assistantBubbles) {
      bubbles.push({ text: b.innerText?.trim()?.substring(0, 100) ?? '' });
    }
    return { spinners, bubbleCount: bubbles.length, bubbles };
  });

  throw new Error(
    `Chat response timeout after ${timeoutMs}ms. Final state: ${JSON.stringify(finalState)}`
  );
}

/**
 * Extract assistant message content and citations from the page.
 */
async function extractAssistantResponse(page) {
  return page.evaluate(() => {
    const assistantBubbles = document.querySelectorAll('[role="log"] .bg-muted');
    const results = [];

    for (const bubble of assistantBubbles) {
      // Get the main text content (excluding citation cards)
      const contentDiv = bubble.querySelector('.whitespace-pre-wrap');
      const contentText = contentDiv?.innerText?.trim() ?? '';

      // Get citations — they are in CitationCard components
      // CitationCard renders a Badge with source text inside a Card
      const _badges = bubble.querySelectorAll('[class*="Badge"]');
      // Badge variant="secondary" renders as a span with specific classes
      // We look for badges within the citations container
      const citationContainer = bubble.querySelector('.mt-3.space-y-2');
      const citations = [];

      if (citationContainer) {
        const cards = citationContainer.querySelectorAll('[class*="border-l-4"]');
        for (const card of cards) {
          const badge = card.querySelector('span, [role="status"]');
          const sourceText = badge?.innerText?.trim() ?? '';
          const link = card.querySelector('a');
          const url = link?.href ?? null;
          const snippet = card.querySelector('.line-clamp-3')?.innerText?.trim() ?? '';
          if (sourceText) {
            citations.push({ source: sourceText, url, snippet });
          }
        }
      }

      // Fallback: look for any Badge-like elements (shadcn badges are spans with badge classes)
      if (citations.length === 0) {
        const allBadges = bubble.querySelectorAll('span[class*="badge"]');
        for (const badge of allBadges) {
          const text = badge.innerText?.trim();
          if (text) {
            citations.push({ source: text, url: null, snippet: '' });
          }
        }
      }

      results.push({ content: contentText, citations });
    }

    return results;
  });
}

// ── Core chat submission test ────────────────────────────────────────────────

test('Chat submission: end-to-end cited answer flow for both locales', async (t) => {
  let browser;
  const results = [];

  try {
    browser = await chromium.launch({ args: ['--no-sandbox'] });

    for (const tc of TEST_CASES) {
      await t.test(tc.label, async () => {
        const context = await browser.newContext({
          viewport: { width: 1280, height: 800 },
        });
        const page = await context.newPage();
        const consoleErrors = collectConsoleErrors(page);

        try {
          // Step 1: Navigate to chat page
          const url = `${BASE_URL}${tc.path}`;
          const response = await page.goto(url, {
            waitUntil: 'networkidle',
            timeout: 15000,
          });

          assert.ok(response, `Response must exist for ${tc.path}`);
          assert.ok(
            response.status() < 400,
            `HTTP ${response.status()} for ${tc.path} must be < 400`
          );

          // Step 2: Verify page loaded with chat interface
          const hasTextarea = await page.locator('textarea').isVisible({ timeout: 5000 });
          assert.ok(hasTextarea, `Chat textarea must be visible on ${tc.path}`);

          // Step 3: Type the test query into the textarea
          await page.locator('textarea').fill(tc.query);
          const inputValue = await page.locator('textarea').inputValue();
          assert.equal(inputValue, tc.query, 'Textarea should contain the typed query');

          // Step 4: Submit via Enter key (reliable across locales, avoids aria-label variation)
          // The send button has locale-dependent aria-label; Enter is universal
          await page.locator('textarea').press('Enter');

          // Step 5: Wait for loading indicator and then response
          await waitForChatResponse(page, 30000);

          // Step 6: Assert assistant response is non-empty
          const assistantMessages = await extractAssistantResponse(page);
          assert.ok(
            assistantMessages.length > 0,
            'At least one assistant message should be present'
          );

          const lastAssistantMsg = assistantMessages[assistantMessages.length - 1];
          assert.ok(
            lastAssistantMsg.content.length > 0,
            `Assistant response must be non-empty (got "${lastAssistantMsg.content.substring(0, 50)}...")`
          );

          // Step 7: Assert at least one citation card renders
          // Citations appear as Badge elements within the assistant message
          const citationCount = lastAssistantMsg.citations.length;
          assert.ok(
            citationCount > 0,
            `At least one citation card should render (found ${citationCount}). ` +
              `Response preview: "${lastAssistantMsg.content.substring(0, 100)}..."`
          );

          // Log citations for diagnostics
          console.log(`  Citations for ${tc.label}:`);
          for (const c of lastAssistantMsg.citations) {
            console.log(`    - ${c.source}${c.url ? ` (${c.url})` : ''}`);
          }

          // Step 8: Assert zero console errors
          assert.deepStrictEqual(
            consoleErrors,
            [],
            `No console errors during chat interaction: ${consoleErrors.join('; ')}`
          );

          results.push({ locale: tc.locale, passed: true, citations: citationCount });
        } catch (err) {
          results.push({ locale: tc.locale, passed: false, error: err.message });
          // Log console errors for diagnostics even if test failed
          if (consoleErrors.length > 0) {
            console.log(`  Console errors for ${tc.label}:`);
            consoleErrors.forEach((e) => console.log(`    - ${e}`));
          }
          throw err;
        } finally {
          await context.close();
        }
      });
    }
  } finally {
    if (browser) await browser.close();
  }

  // Summary
  const passed = results.filter((r) => r.passed).length;
  const failed = results.filter((r) => !r.passed).length;
  console.log(`\nChat submission test: ${passed} passed, ${failed} failed`);
  for (const r of results) {
    if (r.passed) {
      console.log(`  ✓ ${r.locale}: ${r.citations} citation(s)`);
    } else {
      console.log(`  ✗ ${r.locale}: ${r.error}`);
    }
  }
});

// ── Negative test: empty submission should not send ──────────────────────────

test('Chat: empty input should disable send button', async () => {
  let browser;
  try {
    browser = await chromium.launch({ args: ['--no-sandbox'] });
    const context = await browser.newContext({
      viewport: { width: 1280, height: 800 },
    });
    const page = await context.newPage();

    await page.goto(`${BASE_URL}/vi/chat`, {
      waitUntil: 'networkidle',
      timeout: 15000,
    });

    // Wait for textarea
    await page.locator('textarea').waitFor({ state: 'visible', timeout: 5000 });

    // With empty input, send button should be disabled
    // Target the send button by its icon button classes (not the Next.js DevTools button)
    const sendButton = page.locator('button.rounded-xl.h-10.w-10');
    const isDisabled = await sendButton.isDisabled();
    assert.ok(
      isDisabled,
      'Send button should be disabled when textarea is empty'
    );

    // Type something, button should become enabled
    await page.locator('textarea').fill('test');
    const isEnabled = await sendButton.isEnabled();
    assert.ok(isEnabled, 'Send button should be enabled when textarea has content');

    await context.close();
  } finally {
    if (browser) await browser.close();
  }
});

console.log(
  'S04 Chat submission test loaded — verifies end-to-end cited answer flow for /vi/chat and /en/chat'
);
