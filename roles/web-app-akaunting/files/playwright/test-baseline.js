const { test, expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const baseUrl = normalizeBaseUrl(process.env.AKAUNTING_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test("baseline: Akaunting responds on the canonical domain", async ({ page }) => {
  expect(baseUrl, "AKAUNTING_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();

  const r = await page.goto(`${baseUrl}/`);
  expect(r).toBeTruthy();
  expect(r.status()).toBeLessThan(500);
  expect(r.url().includes(canonicalDomain)).toBe(true);
});
