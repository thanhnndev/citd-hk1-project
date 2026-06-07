import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const baseURL = process.env.BASE_URL ?? "http://127.0.0.1:3500";
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
const outputDir = new URL("../test-results/chat-ui/", import.meta.url);

await mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({
  headless: true,
  ...(executablePath ? { executablePath } : {}),
});

for (const check of [
  { name: "desktop", viewport: { width: 1440, height: 900 } },
  { name: "tablet", viewport: { width: 820, height: 1000 } },
  { name: "mobile", viewport: { width: 375, height: 812 } },
]) {
  const page = await browser.newPage({ viewport: check.viewport });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto(`${baseURL}/vi/chat`, { waitUntil: "networkidle" });
  await page.locator("textarea").waitFor({ state: "visible" });

  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth >
      document.documentElement.clientWidth,
  );
  assert.equal(overflow, false, `${check.name} must not overflow horizontally`);
  assert.deepEqual(errors, [], `${check.name} must not emit page errors`);

  await page.screenshot({
    path: fileURLToPath(new URL(`${check.name}.png`, outputDir)),
    fullPage: true,
  });
  await page.close();
}

await browser.close();
console.log("S13 chat visual check passed.");
