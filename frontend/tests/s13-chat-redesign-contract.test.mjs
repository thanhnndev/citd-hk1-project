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
const chatLayout = await readFile(
  new URL("../src/components/chat/chat-interface.module.css", import.meta.url),
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
  /import styles from "\.\/chat-interface\.module\.css";/,
  "chat should use a CSS module for stateful desktop columns",
);
assert.match(
  chat,
  /data-sidebar-open=\{!sidebarCollapsed\}/,
);
assert.match(
  chat,
  /data-panel-open=\{showDesktopPlaces\}/,
);
assert.match(
  chatLayout,
  /\[data-sidebar-open="false"\]\[data-panel-open="true"\][^{]*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+360px/s,
  "collapsed sidebar with an open sources panel should keep the panel in the right desktop column",
);
assert.match(
  chatLayout,
  /\[data-sidebar-open="true"\]\[data-panel-open="true"\][^{]*\{[^}]*grid-template-columns:\s*240px\s+minmax\(0,\s*1fr\)\s+360px/s,
  "open sidebar and sources panel should render three desktop columns",
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
