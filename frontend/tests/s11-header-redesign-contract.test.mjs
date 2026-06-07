import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const siteHeader = await readFile(
  new URL("../src/components/layout/site-header.tsx", import.meta.url),
  "utf8",
);
const navigation = await readFile(
  new URL("../src/components/layout/header-navigation.tsx", import.meta.url),
  "utf8",
).catch(() => "");

assert.match(
  siteHeader,
  /HeaderNavigation/,
  "site header should use route-aware navigation",
);
assert.match(
  siteHeader,
  /data-testid="ham-ninh-logo"/,
  "site header should render the supplied landmark logo",
);
assert.match(siteHeader, /h-16/, "site header should use the approved 64px height");
assert.match(
  navigation,
  /usePathname/,
  "header navigation should detect the current route",
);
assert.match(
  navigation,
  /after:h-\[2px\]/,
  "active navigation should use a 2px underline",
);
assert.doesNotMatch(
  navigation,
  /rounded-lg border/,
  "desktop nav links should be flat text links",
);

console.log("S11 header redesign contract passed.");
