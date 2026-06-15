import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const page = await readFile(
  new URL("../src/app/[locale]/architecture/page.tsx", import.meta.url),
  "utf8",
);

for (const id of [
  "architecture-hero",
  "architecture-flow",
  "rag-pipeline",
  "maps-api",
  "fairness-reranking",
  "orchestration",
  "frontend-shell",
]) {
  assert.match(page, new RegExp(`(id="${id}"|id: '${id}')`), `missing ${id}`);
}

for (const label of [
  "Người dùng",
  "Frontend",
  "Bộ điều phối Agent",
  "Worker",
  "SSE Streaming",
  "Phản hồi",
]) {
  assert.match(page, new RegExp(label), `missing flow node ${label}`);
}

assert.match(page, /Trợ lý AI đa agent cho du lịch Hàm Ninh/);
assert.match(page, /rounded-\[10px\] border border-\[#bfc7d1\] bg-\[#f0f3ff\]/);
assert.match(page, /© 2026 Hàm Ninh Guide AI/);
assert.match(page, /Privacy Policy/);
assert.match(page, /Terms of Service/);
assert.match(page, /Security Disclosure/);
assert.match(page, /max-w-\[960px\]/);
assert.match(page, /style=\{\{ paddingBottom: 72, paddingTop: 92 \}\}/);
assert.match(page, /style=\{\{ maxWidth: 760 \}\}/);
assert.match(page, /fontFamily: '"Be Vietnam Pro", Arial, sans-serif'/);
assert.match(page, /fontSize: 'clamp\(42px, 4vw, 58px\)'/);
assert.match(page, /fontWeight: 800/);
assert.match(page, /letterSpacing: '-0\.025em'/);
assert.match(page, /style=\{\{ fontSize: 16, lineHeight: '28px', maxWidth: 610 \}\}/);
assert.match(page, /overflow-x-auto/);
assert.match(page, /grid-cols-6/);
assert.match(page, /#005d90/);
assert.match(page, /#E5E7EB/);
assert.doesNotMatch(page, /_ICON_NAME/);
assert.doesNotMatch(page, /ICON_NAME/);
assert.doesNotMatch(page, /blur-3xl/);
assert.doesNotMatch(page, /inline-flex rounded-full/);
assert.doesNotMatch(page, /SectionShell/);
assert.doesNotMatch(page, /SiteFooter/);
assert.doesNotMatch(page, /PlaceholderPage/);

console.log("S14 architecture redesign contract passed.");
