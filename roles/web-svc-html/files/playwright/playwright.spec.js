const { test, expect } = require("@playwright/test");

const {
  apiGetOnion,
  decodeDotenvQuotedValue,
  expectHstsWhenTls,
  gotoOnion,
  normalizeBaseUrl,
  runGuestFlow,
} = require("./personas");
const { resolveTimeout } = require("./timeouts");

test.use({ ignoreHTTPSErrors: true });

const ROOT_STATUS = [200, 403];
const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const imprintUrl = decodeDotenvQuotedValue(process.env.IMPRINT_URL || "");

test.beforeEach(async ({ page }) => {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("html vhost answers under the canonical domain with TLS", async ({ page }) => {
  const response = await gotoOnion(page, `${appBaseUrl}/`);
  expect(response, "Expected a response from the vhost root").toBeTruthy();
  expect(ROOT_STATUS, `the vhost root answered ${response.status()}`).toContain(response.status());
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the vhost URL`,
  ).toBe(true);
  const headers = response.headers();
  expect(headers["content-type"] || "", "the vhost root must answer with HTML").toContain("text/html");
  expect(headers["content-security-policy"], "the vhost root must emit a Content-Security-Policy").toBeTruthy();
  expectHstsWhenTls(headers, appBaseUrl, "html");
});

test("imprint is served as an HTML document", async ({ request }) => {
  test.skip(!imprintUrl, "IMPRINT_URL is empty: web-svc-legal is not deployed");
  const response = await apiGetOnion(request, imprintUrl, { timeout: resolveTimeout(30_000) });
  expect(response.status(), "the imprint must answer 200").toBe(200);
  expect(response.headers()["content-type"] || "", "the imprint must answer with HTML").toContain("text/html");
  expect(await response.text(), "the imprint must carry its heading").toContain("<h1>");
});

test("guest: vhost root → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

require("./test-design").register();
