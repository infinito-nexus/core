const { test, expect } = require("@playwright/test");
const { normalizeBaseUrl, decodeDotenvQuotedValue, gotoOnion } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.YOURLS_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.use({ ignoreHTTPSErrors: true });

test("baseline: YOURLS responds on the canonical domain", async ({ page }) => {
  expect(baseUrl, "YOURLS_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();

  const response = await gotoOnion(page, `${baseUrl}/`);
  expect(response, "Expected YOURLS response").toBeTruthy();
  expect(response.status(), "Expected YOURLS status < 500").toBeLessThan(500);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the YOURLS URL`,
  ).toBe(true);
});
