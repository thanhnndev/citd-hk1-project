import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const page = await readFile(
  new URL("../src/app/[locale]/auth/verify-email/page.tsx", import.meta.url),
  "utf8",
);
const form = await readFile(
  new URL("../src/components/auth/verify-email-form.tsx", import.meta.url),
  "utf8",
);

assert.doesNotMatch(page, /AuthCard/);
assert.match(page, /min-h-screen/);
assert.match(page, /bg-\[#f9f9ff\]/);
assert.match(page, /max-w-md/);
assert.match(page, /p-8 shadow-lg md:p-12/);
assert.match(page, /rounded-xl bg-white/);
assert.match(page, /border-\[#cde5ff\]/);

assert.match(form, /Array\.from\(\{ length: 6 \}\)/);
assert.match(form, /style=\{\{ height: 44, minWidth: 44, width: 44 \}\}/);
assert.doesNotMatch(form, /h-\[68px\]|size-\[68px\]/);
assert.match(form, /flex justify-center gap-2/);
assert.match(form, /border-\[#707881\]/);
assert.match(form, /border-\[#005d90\]/);
assert.match(form, /py-4 text-base font-semibold/);
assert.match(form, /shadow-lg shadow-\[#0077b6\]\/20/);
assert.match(form, /RefreshCw/);
assert.match(form, /text-\[#005d90\]/);
assert.doesNotMatch(page + form, /@\/.*backend|fetch\(|axios/);

console.log("S17 OTP redesign contract passed.");
