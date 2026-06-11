import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { chromium } from "@playwright/test";

const BASE_URL = process.env.FRONTEND_URL ?? "http://localhost:3000";
const MOBILE_CONTEXT = {
  viewport: { width: 375, height: 812 },
  hasTouch: true,
  isMobile: true,
};

let browser;

before(async () => {
  browser = await chromium.launch({ args: ["--no-sandbox"] });
});

after(async () => {
  await browser.close();
});

async function openMobileChat() {
  const context = await browser.newContext(MOBILE_CONTEXT);
  const page = await context.newPage();
  await page.goto(`${BASE_URL}/en/chat`, {
    waitUntil: "networkidle",
    timeout: 20_000,
  });
  await page.locator("textarea").waitFor({ state: "visible" });
  return { context, page };
}

async function mockCitedResponse(page) {
  await page.route(/.*\/api\/chat\/stream.*/, async (route) => {
    const citations = [
      {
        source: "Ham Ninh Tourism Board",
        url: "https://example.com/ham-ninh",
        snippet: "Local travel guidance.",
      },
    ];

    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      headers: {
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
      body: [
        "data: [STATUS] planning",
        "data: A cited answer.",
        `data: [CITATIONS] ${JSON.stringify(citations)}`,
        "data: [DONE]",
        "",
      ].join("\n\n"),
    });
  });
}

test("mobile header button opens and closes the chat sidebar", async () => {
  const { context, page } = await openMobileChat();

  try {
    const dialog = page.getByRole("dialog", { name: "Chat navigation" });
    await page.getByTestId("sidebar-toggle").click();
    await dialog.waitFor({ state: "visible", timeout: 2_000 });

    await dialog.getByRole("button", { name: "Close menu" }).last().click();
    await dialog.waitFor({ state: "hidden", timeout: 2_000 });

    await page.getByTestId("sidebar-toggle").click();
    await dialog.waitFor({ state: "visible", timeout: 2_000 });
    await page.touchscreen.tap(360, 400);
    await dialog.waitFor({ state: "hidden", timeout: 2_000 });
  } finally {
    await context.close();
  }
});

test("mobile header button opens and closes the sources panel", async () => {
  const context = await browser.newContext(MOBILE_CONTEXT);
  const page = await context.newPage();
  await mockCitedResponse(page);

  try {
    await page.goto(`${BASE_URL}/en/chat`, {
      waitUntil: "networkidle",
      timeout: 20_000,
    });

    const textarea = page.locator("textarea");
    await textarea.fill("Show a cited answer");
    await textarea.press("Enter");

    await page.getByText(/^Response time:/).waitFor({
      state: "visible",
      timeout: 5_000,
    });

    const sourcesToggle = page.getByTestId("sources-toggle");
    await sourcesToggle.waitFor({ state: "visible", timeout: 5_000 });
    await sourcesToggle.click();

    const dialog = page.getByRole("dialog", { name: /Recommended|Places|Sources/i });
    await dialog.waitFor({ state: "visible", timeout: 2_000 });
    assert.equal(await dialog.getByText("Ham Ninh Tourism Board").isVisible(), true);

    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await dialog.waitFor({ state: "hidden", timeout: 2_000 });

    await sourcesToggle.click();
    await dialog.waitFor({ state: "visible", timeout: 2_000 });
    await page.touchscreen.tap(10, 400);
    await dialog.waitFor({ state: "hidden", timeout: 2_000 });
  } finally {
    await context.close();
  }
});
