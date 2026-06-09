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
  "Agent Orchestrator",
  "Worker",
  "SSE Streaming",
  "Phản hồi",
]) {
  assert.match(page, new RegExp(label), `missing flow node ${label}`);
}

assert.match(page, /max-w-6xl/);
assert.match(page, /overflow-x-auto/);
assert.match(page, /grid-cols-6/);
assert.match(page, /#005d90/);
assert.match(page, /#E5E7EB/);
assert.doesNotMatch(page, /SectionShell/);
assert.doesNotMatch(page, /SiteFooter/);
assert.doesNotMatch(page, /PlaceholderPage/);

console.log("S14 architecture redesign contract passed.");
