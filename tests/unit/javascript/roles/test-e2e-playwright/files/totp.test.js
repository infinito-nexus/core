const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../..");
const { totpCode } = require(path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/totp.js"));

const RFC_6238_SHA1_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ";
const RFC_6238_SHA1_VECTORS = [
  [59, "287082"],
  [1111111109, "081804"],
  [1111111111, "050471"],
  [1234567890, "005924"],
  [2000000000, "279037"],
  [20000000000, "353130"],
];

test("every RFC 6238 SHA-1 vector comes out as its last six digits", () => {
  for (const [seconds, code] of RFC_6238_SHA1_VECTORS) {
    assert.equal(totpCode(RFC_6238_SHA1_SECRET, seconds * 1000), code, `T=${seconds}`);
  }
});
