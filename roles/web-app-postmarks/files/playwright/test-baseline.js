const { test, expect } = require("@playwright/test");
const { normalizeBaseUrl, decodeDotenvQuotedValue } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.POSTMARKS_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.use({ ignoreHTTPSErrors: true });

test("baseline: Postmarks responds on the canonical domain", async ({ page }) => {
  expect(baseUrl, "POSTMARKS_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();

  const response = await page.goto(`${baseUrl}/`);
  expect(response, "Expected Postmarks response").toBeTruthy();
  expect(response.status(), "Expected Postmarks status < 500").toBeLessThan(500);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the Postmarks URL`,
  ).toBe(true);
});
