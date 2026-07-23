const { test, expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, expectHstsWhenTls, gotoOnion, normalizeBaseUrl } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const mirrorBaseUrl = normalizeBaseUrl(process.env.MIRROR_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

test.beforeEach(async ({ page }) => {
  expect(mirrorBaseUrl, "MIRROR_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("mirror is served under canonical domain and refuses unmapped paths", async ({ page }) => {
  const response = await gotoOnion(page, `${mirrorBaseUrl}/`);
  expect(response, "Expected mirror root response").toBeTruthy();
  expect(response.status(), "Expected mirror root to refuse unmapped paths").toBe(404);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the mirror URL`
  ).toBe(true);
  const headers = response.headers();
  expectHstsWhenTls(headers, mirrorBaseUrl, "Mirror");
});

test("mirror refuses origins outside the CSP-derived allowlist", async ({ page }) => {
  const response = await gotoOnion(page, `${mirrorBaseUrl}/evil.example/payload.js`);
  expect(response, "Expected mirror allowlist response").toBeTruthy();
  expect(
    response.status(),
    "Expected a non-whitelisted origin path to be refused"
  ).toBe(404);
});
