import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const page = await readFile(
  new URL("../src/app/[locale]/chat/page.tsx", import.meta.url),
  "utf8",
);
const chat = await readFile(
  new URL("../src/components/chat/chat-interface.tsx", import.meta.url),
  "utf8",
);
const sidebar = await readFile(
  new URL("../src/components/chat/chat-sidebar.tsx", import.meta.url),
  "utf8",
).catch(() => "");
const places = await readFile(
  new URL("../src/components/chat/place-results-panel.tsx", import.meta.url),
  "utf8",
).catch(() => "");

assert.match(
  page,
  /<ChatInterface locale=\{locale\} translations=\{translations\} \/>/,
);
assert.match(chat, /ChatSidebar/);
assert.match(chat, /PlaceResultsPanel/);
assert.match(
  chat,
  /lg:grid-cols-\[240px_minmax\(0,1fr\)_360px\]/,
);
assert.match(chat, /latestPlaces\.length > 0/);
assert.match(
  chat,
  /messages\.length > 0 && \(isNearBottom \|\| loading\)/,
  "empty welcome screen should not auto-scroll to the bottom",
);
assert.match(sidebar, /newQuestion/);
assert.match(places, /PlaceCard/);
assert.match(places, /PlaceResult/);
assert.doesNotMatch(chat + sidebar + places, /@\/.*backend|fetch\(|axios/);

console.log("S13 chat redesign contract passed.");
