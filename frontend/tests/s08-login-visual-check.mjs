import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const BASE_URL = process.env.FRONTEND_URL ?? "http://127.0.0.1:3000";
const executablePath =
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined;
const outputDir = fileURLToPath(
  new URL("../test-results/login-ui/", import.meta.url),
);

await mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({
  args: ["--no-sandbox"],
  executablePath,
});

try {
  for (const route of [
    { name: "login", path: "/vi/auth/login" },
    { name: "register", path: "/vi/auth/register" },
  ]) {
    for (const viewport of [
      { name: "desktop", width: 1440, height: 900 },
      { name: "mobile", width: 390, height: 844 },
    ]) {
      const context = await browser.newContext({
        viewport: { width: viewport.width, height: viewport.height },
      });
      const page = await context.newPage();
      const consoleErrors = [];
      const failedResources = [];

      page.on("console", (message) => {
        if (
          message.type() === "error" &&
          !message.text().startsWith("Failed to load resource:")
        ) {
          consoleErrors.push(message.text());
        }
      });
      page.on("pageerror", (error) => consoleErrors.push(error.message));
      page.on("response", (response) => {
        if (
          response.status() >= 400 &&
          !new URL(response.url()).pathname.endsWith("/favicon.ico")
        ) {
          failedResources.push(`${response.status()} ${response.url()}`);
        }
      });

      await page.goto(`${BASE_URL}${route.path}`, {
        waitUntil: "networkidle",
        timeout: 20_000,
      });

      await page.screenshot({
        path: `${outputDir}/${route.name}-${viewport.name}.png`,
        fullPage: true,
      });

      const dimensions = await page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      }));

      assert.equal(
        dimensions.scrollWidth,
        dimensions.clientWidth,
        `${viewport.name} ${route.name} must not overflow horizontally`,
      );
      assert.deepEqual(
        consoleErrors,
        [],
        `${viewport.name} ${route.name} should have no console errors`,
      );
      assert.deepEqual(
        failedResources,
        [],
        `${viewport.name} ${route.name} should load all page resources`,
      );
      await context.close();
    }
  }

  console.log("S08 auth visual check passed.");
} finally {
  await browser.close();
}
