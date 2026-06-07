import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const registerPage = await readFile(
  new URL("../src/app/[locale]/auth/register/page.tsx", import.meta.url),
  "utf8",
);
const registerShell = await readFile(
  new URL("../src/components/auth/register-shell.tsx", import.meta.url),
  "utf8",
).catch(() => "");
const registerForm = await readFile(
  new URL("../src/components/auth/register-form.tsx", import.meta.url),
  "utf8",
);

assert.match(
  registerPage,
  /RegisterShell/,
  "register route should use a dedicated shell",
);
assert.match(
  registerShell,
  /lg:grid-cols-\[40%_60%\]/,
  "desktop registration should use the approved 40/60 split",
);
assert.match(
  registerForm,
  /id="confirm_password"/,
  "registration should confirm the password on the client",
);
assert.match(
  registerForm,
  /password !== confirmPassword/,
  "registration should reject mismatched passwords before API submission",
);
assert.match(
  registerForm,
  /register\(\{ username, email, password \}\)/,
  "registration API payload must remain unchanged",
);
assert.doesNotMatch(
  registerForm,
  /register\(\{[^}]*confirmPassword/,
  "confirm password must never be sent to the backend",
);

console.log("S09 register UI contract passed.");
