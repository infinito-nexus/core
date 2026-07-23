const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { normalizeBaseUrl, decodeDotenvQuotedValue , expectHstsWhenTls, gotoOnion } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.SNIPE_IT_BASE_URL || process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.use({ ignoreHTTPSErrors: true });

test("baseline: Snipe-IT front page is served under the canonical domain with TLS", async ({ page }) => {
  expect(baseUrl, "SNIPE_IT_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();

  const response = await gotoOnion(page, `${baseUrl}/`);
  expect(response, "Expected Snipe-IT response").toBeTruthy();
  expect(response.status(), "Expected Snipe-IT front page status < 500").toBeLessThan(500);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the Snipe-IT URL`,
  ).toBe(true);
  const headers = response.headers();
  expectHstsWhenTls(headers, baseUrl, "Snipe-IT");
});

test("baseline: Snipe-IT returns HTML content under the canonical domain", async ({ request }) => {
  expect(baseUrl, "SNIPE_IT_BASE_URL must be set").toBeTruthy();
  const response = await request.get(`${baseUrl}/`, { timeout: resolveTimeout(30_000) });
  expect(response.status(), "Expected Snipe-IT front page status < 500").toBeLessThan(500);
  const contentType = response.headers()["content-type"] || "";
  expect(
    contentType.includes("text/html"),
    `Expected HTML content-type, got "${contentType}"`,
  ).toBe(true);
});
