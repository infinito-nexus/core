const { test, expect } = require("@playwright/test");
const { normalizeBaseUrl, decodeDotenvQuotedValue, gotoOnion } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.BOOKWYRM_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.use({ ignoreHTTPSErrors: true });

test("baseline: BookWyrm responds on the canonical domain", async ({ page }) => {
  expect(baseUrl, "BOOKWYRM_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();

  const response = await gotoOnion(page, `${baseUrl}/`);
  expect(response).toBeTruthy();
  expect(response.status()).toBeLessThan(500);
  expect(response.url().includes(canonicalDomain)).toBe(true);
});
