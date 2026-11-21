const { test, expect } = require("@playwright/test");
const {
  gotoOnion,
  normalizeBaseUrl,
  requireDotenvValue,
} = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.WORKSPACE_BASE_URL || "");
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");

test.use({ ignoreHTTPSErrors: true });

test("baseline: the workspace IDE responds on the canonical domain", async ({ page }) => {
  expect(baseUrl, "WORKSPACE_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();

  const response = await gotoOnion(page, `${baseUrl}/`);
  expect(response, "Expected a workspace response").toBeTruthy();
  expect(response.status(), "Expected workspace status < 500").toBeLessThan(500);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the workspace URL`,
  ).toBe(true);
});
