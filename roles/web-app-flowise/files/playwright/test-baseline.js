const { test, expect } = require("@playwright/test");
const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.FLOWISE_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.use({ ignoreHTTPSErrors: true });

test("baseline: Flowise responds on the canonical domain", async ({ page }) => {
  expect(baseUrl, "FLOWISE_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();

  const response = await page.goto(`${baseUrl}/`);
  expect(response, "Expected Flowise response").toBeTruthy();
  expect(response.status(), "Expected Flowise status < 500").toBeLessThan(500);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the Flowise URL`
  ).toBe(true);
});
