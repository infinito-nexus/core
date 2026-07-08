const { test, expect } = require("@playwright/test");
const { normalizeBaseUrl, decodeDotenvQuotedValue, gotoOnion } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.BASEROW_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.use({ ignoreHTTPSErrors: true });

test("baseline: Baserow responds on the canonical domain", async ({ page }) => {
  expect(baseUrl, "BASEROW_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();

  const response = await gotoOnion(page, `${baseUrl}/`);
  expect(response, "Expected Baserow response").toBeTruthy();
  expect(response.status(), "Expected Baserow status < 500").toBeLessThan(500);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the Baserow URL`,
  ).toBe(true);
});
