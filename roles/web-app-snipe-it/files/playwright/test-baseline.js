const { test, expect } = require("@playwright/test");
const { normalizeBaseUrl, decodeDotenvQuotedValue } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.SNIPE_IT_BASE_URL || process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.use({ ignoreHTTPSErrors: true });

test("baseline: Snipe-IT front page is served under the canonical domain with TLS", async ({ page }) => {
  expect(baseUrl, "SNIPE_IT_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();

  const response = await page.goto(`${baseUrl}/`);
  expect(response, "Expected Snipe-IT response").toBeTruthy();
  expect(response.status(), "Expected Snipe-IT front page status < 500").toBeLessThan(500);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the Snipe-IT URL`,
  ).toBe(true);
  const headers = response.headers();
  expect(headers["strict-transport-security"], "Snipe-IT must emit HSTS").toBeTruthy();
});

test("baseline: Snipe-IT returns HTML content under the canonical domain", async ({ request }) => {
  expect(baseUrl, "SNIPE_IT_BASE_URL must be set").toBeTruthy();
  const response = await request.get(`${baseUrl}/`);
  expect(response.status(), "Expected Snipe-IT front page status < 500").toBeLessThan(500);
  const contentType = response.headers()["content-type"] || "";
  expect(
    contentType.includes("text/html"),
    `Expected HTML content-type, got "${contentType}"`,
  ).toBe(true);
});
