const { test, expect } = require("@playwright/test");
const { normalizeBaseUrl, decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const baseUrl = normalizeBaseUrl(process.env.OPENBAO_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.use({ ignoreHTTPSErrors: true });

test("baseline: OpenBao responds on the canonical domain and serves its UI", async ({ page }) => {
  expect(baseUrl, "OPENBAO_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();

  const response = await gotoOnion(page, `${baseUrl}/`);
  expect(response, "Expected OpenBao response").toBeTruthy();
  expect(response.status(), "Expected OpenBao status < 500").toBeLessThan(500);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the OpenBao URL`,
  ).toBe(true);

  // "/" redirects into the Ember UI; the auth surface is the only unauthenticated one.
  await expect
    .poll(() => page.url(), { message: "expected OpenBao to redirect into /ui/" })
    .toContain("/ui/");
});

test("baseline: the API reports an initialised, unsealed node", async ({ request }) => {
  const response = await request.get(`${baseUrl}/v1/sys/health`, {
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  // 200 = initialised, unsealed, active. 503 = sealed, 501 = uninitialised.
  expect(
    response.status(),
    `expected /v1/sys/health to report an unsealed active node, got ${response.status()}`,
  ).toBe(200);

  const health = await response.json();
  expect(health.initialized, "OpenBao must be initialised").toBe(true);
  expect(health.sealed, "OpenBao must be auto-unsealed by the static seal").toBe(false);
});
