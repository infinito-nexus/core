const { test, expect } = require("@playwright/test");

const { appBaseUrl, canonicalDomain, attachDiagnostics, setupMatomoPage } = require("./_shared");
const { assertCspMetaParity, assertCspResponseHeader, expectNoCspViolations } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(async ({ page }) => {
  await setupMatomoPage(page);
});

test("matomo enforces Content-Security-Policy and exposes canonical domain from applications lookup", async ({ page }) => {
  const diagnostics = attachDiagnostics(page);

  const response = await page.goto(`${appBaseUrl}/`);
  expect(response, "Expected Matomo login response").toBeTruthy();
  expect(response.status(), "Expected Matomo login response to be successful").toBeLessThan(400);

  const directives = assertCspResponseHeader(response, "matomo login");
  await assertCspMetaParity(page, directives, "matomo login");

  const documentHtml = await response.text();
  const documentUrl = response.url();
  expect(
    documentHtml.includes(canonicalDomain) || documentUrl.includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" (from applications lookup) to appear in the Matomo login document`
  ).toBe(true);

  await expectNoCspViolations(page, diagnostics, "matomo login");
});
