import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const loginPage = await readFile(
  new URL("../src/app/[locale]/auth/login/page.tsx", import.meta.url),
  "utf8",
);
const loginShell = await readFile(
  new URL("../src/components/auth/login-shell.tsx", import.meta.url),
  "utf8",
).catch(() => "");
const loginForm = await readFile(
  new URL("../src/components/auth/login-form.tsx", import.meta.url),
  "utf8",
);
const viMessages = await readFile(
  new URL("../messages/vi.json", import.meta.url),
  "utf8",
);
const enMessages = await readFile(
  new URL("../messages/en.json", import.meta.url),
  "utf8",
);

assert.match(loginPage, /LoginShell/, "login route should use the dedicated shell");
assert.match(
  loginShell,
  /lg:grid-cols-\[40%_60%\]/,
  "desktop login should use the approved 40/60 split",
);
assert.match(
  loginShell,
  /data-testid="login-hero"/,
  "login shell should include the Phu Quoc hero",
);
assert.match(loginForm, /id="email"/, "email field ID must remain stable");
assert.match(loginForm, /id="password"/, "password field ID must remain stable");
assert.match(
  loginForm,
  /border-b/,
  "login fields should use the approved underlined treatment",
);
assert.match(
  viMessages,
  /"rememberLogin"/,
  "Vietnamese login copy should include remember-login",
);
assert.match(
  enMessages,
  /"rememberLogin"/,
  "English login copy should include remember-login",
);

console.log("S08 login UI contract passed.");
