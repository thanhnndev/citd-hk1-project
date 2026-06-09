import assert from "node:assert/strict";
import { chromium } from "@playwright/test";

const baseURL = process.env.BASE_URL ?? "http://127.0.0.1:3000";
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
const browser = await chromium.launch({
  headless: true,
  ...(executablePath ? { executablePath } : {}),
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
});

const conversations = [
  {
    id: "layout-test",
    sessionId: "layout-test-session",
    title: "Layout test",
    updatedAt: Date.now(),
    messages: [
      { role: "user", content: "Tìm quán ăn", status: "complete" },
      {
        role: "assistant",
        content: "Đây là địa điểm gợi ý.",
        places: [
          {
    place_id: "layout-test-place",
    display_name: "Nhà bè Thảo Nhi",
    formatted_address: "Hàm Ninh, Phú Quốc",
    types: ["seafood_restaurant"],
    rating: 4.9,
    user_rating_count: 90,
    open_now: true,
    payment_options: {},
    parking_options: {},
    reviews: [],
    photos: [],
    service_options: {},
    local_factor: 1,
    final_score: 0.9,
    score_breakdown: {},
    map_uri: "https://maps.example.test/place",
          },
        ],
        status: "complete",
      },
    ],
  },
];

try {
  const page = await context.newPage();
  await page.goto(`${baseURL}/vi/chat`, { waitUntil: "networkidle" });
  await page.evaluate((storedConversations) => {
    localStorage.removeItem("ham_ninh_token");
    localStorage.removeItem("ham_ninh_user");
    localStorage.setItem(
      "ham_ninh_chat_v1:guest",
      JSON.stringify(storedConversations),
    );
  }, conversations);
  await page.reload({ waitUntil: "networkidle" });

  const layout = page.getByTestId("chat-layout");
  const main = page.getByTestId("chat-main");
  const panel = page.getByTestId("desktop-evidence-panel");

  await layout.waitFor({ state: "visible" });
  await page.getByText("Đây là địa điểm gợi ý.").waitFor({ state: "visible" });
  await panel.waitFor({ state: "visible" });
  await page.getByTestId("sidebar-toggle").click();
  await layout.evaluate(() =>
    new Promise((resolve) => requestAnimationFrame(() => resolve())),
  );

  assert.equal(await layout.getAttribute("data-sidebar-open"), "false");
  assert.equal(await layout.getAttribute("data-panel-open"), "true");

  const [mainBox, panelBox, columns] = await Promise.all([
    main.boundingBox(),
    panel.boundingBox(),
    layout.evaluate((element) => getComputedStyle(element).gridTemplateColumns),
  ]);

  assert.ok(mainBox, "chat main must be visible");
  assert.ok(panelBox, "desktop evidence panel must be visible");
  assert.ok(
    Math.abs(panelBox.y - mainBox.y) <= 1,
    "panel must stay on the same row as the chat",
  );
  assert.ok(
    panelBox.x >= mainBox.x + mainBox.width - 1,
    "panel must be positioned to the right of the chat",
  );
  assert.ok(
    Math.abs(panelBox.width - 360) <= 1,
    "desktop evidence panel must remain 360px wide",
  );
  assert.match(columns, /360px$/, "desktop grid must end with the panel column");
} finally {
  await context.close();
  await browser.close();
}

console.log("S13 chat panel layout visual check passed.");
