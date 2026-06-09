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
assert.match(chat, /const \[sidebarCollapsed, setSidebarCollapsed\] = useState\(false\);/);
assert.match(chat, /const \[placesPanelOpen, setPlacesPanelOpen\] = useState\(true\);/);
assert.match(chat, /sidebarCollapsed/);
assert.match(chat, /placesPanelOpen/);
assert.match(chat, /setSidebarCollapsed\(\(current\) => !current\)/);
assert.match(chat, /setPlacesPanelOpen\(\(current\) => !current\)/);
assert.match(
  chat,
  /lg:grid-cols-\[240px_minmax\(0,1fr\)_360px\]/,
);
assert.match(
  chat,
  /lg:grid-cols-\[minmax\(0,1fr\)_360px\]/,
  "chat should support a collapsed desktop sidebar while sources stay open",
);
assert.match(
  chat,
  /lg:grid-cols-\[240px_minmax\(0,1fr\)\]/,
  "chat should support a closed desktop sources panel while sidebar stays open",
);
assert.match(
  chat,
  /lg:grid-cols-\[minmax\(0,1fr\)\]/,
  "chat should support both desktop panels being closed",
);
assert.match(chat, /desktopOpen=\{!sidebarCollapsed\}/);
assert.match(chat, /onDesktopToggle=\{\(\) => setSidebarCollapsed\(\(current\) => !current\)\}/);
assert.match(chat, /desktopOpen=\{placesPanelOpen\}/);
assert.match(chat, /onDesktopClose=\{\(\) => setPlacesPanelOpen\(false\)\}/);
assert.match(chat, /aria-label=\{sidebarToggleLabel\}/);
assert.match(chat, /aria-label=\{sourcesToggleLabel\}/);
assert.match(chat, /latestPlaces\.length > 0/);
assert.match(
  chat,
  /messages\.length > 0 && \(isNearBottom \|\| loading\)/,
  "empty welcome screen should not auto-scroll to the bottom",
);
assert.doesNotMatch(
  chat,
  /<header className="relative z-10 flex h-14/,
  "chat page should not render a second internal top header",
);
assert.match(sidebar, /newQuestion/);
assert.match(sidebar, /desktopOpen: boolean/);
assert.match(sidebar, /onDesktopToggle: \(\) => void/);
assert.match(sidebar, /lg:hidden/);
assert.match(places, /PlaceCard/);
assert.match(places, /PlaceResult/);
assert.match(places, /desktopOpen: boolean/);
assert.match(places, /onDesktopClose: \(\) => void/);
assert.match(places, /onDesktopClose/);
assert.doesNotMatch(chat + sidebar + places, /@\/.*backend|fetch\(|axios/);

console.log("S13 chat redesign contract passed.");
