const { test, expect } = require("@playwright/test");
const {
  assertCspMetaParity,
  assertCspResponseHeader,
  attachDiagnostics,
  expectNoCspViolations,
  gotoOnion,
  normalizeBaseUrl,
  requireDotenvValue,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
} = require("./personas");
const { resolveTimeout } = require("./timeouts");

const appBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
const apiToken = requireDotenvValue(process.env.WEBLATE_API_TOKEN, "WEBLATE_API_TOKEN");

test.use({ ignoreHTTPSErrors: true });

test("weblate serves its login surface under a Content-Security-Policy", async ({ page }) => {
  const diagnostics = attachDiagnostics(page);

  const response = await gotoOnion(page, `${appBaseUrl}/`);
  expect(response, "Expected a Weblate response").toBeTruthy();
  expect(response.status(), "Expected the Weblate entry page to answer").toBeLessThan(400);

  const directives = assertCspResponseHeader(response, "weblate entry");
  await assertCspMetaParity(page, directives, "weblate entry");
  expect(response.url(), "Expected the canonical Weblate domain").toContain(canonicalDomain);

  await expectNoCspViolations(page, diagnostics, "weblate entry");
});

test("the token the gateway was handed reads the API", async ({ request }) => {
  const response = await request.get(`${appBaseUrl}/api/projects/`, {
    headers: { Authorization: `Token ${apiToken}` },
    failOnStatusCode: false,
    timeout: resolveTimeout(120_000),
  });

  expect(response.status(), "Expected the stored token to authenticate against Weblate").toBe(200);
  expect(Array.isArray((await response.json()).results), "Expected a project listing").toBe(true);
});

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page);
});
