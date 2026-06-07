import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const bubble = await readFile(
  new URL("../src/components/chat/message-bubble.tsx", import.meta.url),
  "utf8",
);

assert.match(
  bubble,
  /import ReactMarkdown(?:,\s*\{[^}]*Components[^}]*\})? from "react-markdown"/,
);
assert.match(bubble, /components=\{markdownComponents\}/);
assert.match(bubble, /transformCitationMarkers/);
assert.match(bubble, /strong:/);
assert.match(bubble, /ul:/);
assert.match(bubble, /ol:/);
assert.match(bubble, /code:/);
assert.match(bubble, /blockquote:/);
assert.match(bubble, /target="_blank"/);
assert.doesNotMatch(bubble, /rehypeRaw|rehype-raw/);

console.log("S13 chat markdown contract passed.");
