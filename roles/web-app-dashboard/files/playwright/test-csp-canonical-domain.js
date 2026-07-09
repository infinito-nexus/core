const { test, expect } = require("./fixtures/onion-test");

const {
  assertCspMetaParity,
  assertCspResponseHeader,
  decodeDotenvQuotedValue,
  expectNoCspViolations,
  installCspViolationObserver,
  gotoOnion,
} = require("./personas");

const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

exports.register = function (shared) {
  test.beforeEach(async ({ page }) => {
    await installCspViolationObserver(page);
  });

  test("dashboard enforces Content-Security-Policy and exposes canonical domain from applications lookup", async ({ page }) => {
    const response = await gotoOnion(page,"/");
    expect(response, "Expected dashboard landing response").toBeTruthy();
    expect(response.status(), "Expected dashboard landing response to be successful").toBeLessThan(400);

    const directives = assertCspResponseHeader(response, "dashboard landing");
    await assertCspMetaParity(page, directives, "dashboard landing");

    const documentHtml = await response.text();
    const documentUrl = response.url();
    expect(
      documentHtml.includes(canonicalDomain) || documentUrl.includes(canonicalDomain),
      `Expected canonical domain "${canonicalDomain}" (from applications lookup) to appear in the dashboard document`
    ).toBe(true);

    await shared.waitForDashboardReady(page);
    await expectNoCspViolations(page, null, "dashboard landing");
  });
};
