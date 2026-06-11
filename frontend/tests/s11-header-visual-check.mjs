import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const BASE_URL = process.env.FRONTEND_URL ?? "http://127.0.0.1:3500";
const outputDir = fileURLToPath(
  new URL("../test-results/header-ui/", import.meta.url),
);

await mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({
  args: ["--no-sandbox"],
  executablePath:
    process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
});

try {
  for (const viewport of [
    { name: "desktop", width: 1440, height: 900 },
    { name: "mobile", width: 390, height: 844 },
  ]) {
    const context = await browser.newContext({
      viewport: { width: viewport.width, height: viewport.height },
      hasTouch: viewport.name === "mobile",
      isMobile: viewport.name === "mobile",
    });
    const page = await context.newPage();
    const errors = [];

    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`${BASE_URL}/vi/architecture`, {
      waitUntil: "networkidle",
      timeout: 20_000,
    });
    await page.waitForTimeout(800);

    await page.screenshot({
      path: `${outputDir}/${viewport.name}.png`,
      clip: { x: 0, y: 0, width: viewport.width, height: 180 },
    });

    const dimensions = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));

    assert.equal(
      dimensions.scrollWidth,
      dimensions.clientWidth,
      `${viewport.name} header must not overflow horizontally`,
    );

    if (viewport.name === "mobile") {
      const registerLink = page.locator('a[href$="/auth/register"]');
      await registerLink.click({ timeout: 3_000 });
      await page.waitForURL("**/vi/auth/register", { timeout: 3_000 });
    }

    assert.deepEqual(errors, [], `${viewport.name} header should not throw`);
    await context.close();
  }

  console.log("S11 header visual check passed.");
} finally {
  await browser.close();
}
