import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const page = await readFile(
  new URL("../src/app/[locale]/page.tsx", import.meta.url),
  "utf8",
);
const homepage = await readFile(
  new URL("../src/components/landing/tourism-homepage.tsx", import.meta.url),
  "utf8",
).catch(() => "");

assert.match(page, /TourismHomepage/, "homepage route should use the tourism design");
for (const id of [
  "homepage-hero",
  "homepage-stats",
  "homepage-benefits",
  "homepage-steps",
  "homepage-cta",
]) {
  assert.match(homepage, new RegExp(`id="${id}"`), `homepage should include ${id}`);
}
assert.match(homepage, /href="\/chat"/, "primary homepage CTA should open chat");
assert.match(
  homepage,
  /\/images\/ham-ninh-homepage\.jpg/,
  "homepage should use a local Ham Ninh image",
);

console.log("S10 homepage redesign contract passed.");
