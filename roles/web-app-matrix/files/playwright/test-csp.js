const { test, expect } = require("@playwright/test");
const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("matrix element enforces Content-Security-Policy and exposes canonical domain from applications lookup", async ({ page }) => {
    const { elementBaseUrl, canonicalDomain } = shared.env;
    const diagnostics = shared.attachDiagnostics(page);
    const response = await gotoOnion(page, `${elementBaseUrl}/`);
    expect(response, "Expected element landing response").toBeTruthy();
    expect(response.status(), "Expected element landing status < 400").toBeLessThan(400);
    shared.assertCspResponseHeader(response, "matrix element landing");
    const documentUrl = response.url();
    expect(
      documentUrl.includes(canonicalDomain),
      `Expected canonical domain "${canonicalDomain}" to back the element URL`,
    ).toBe(true);
    await shared.expectNoCspViolations(page, diagnostics, "matrix element landing");
  });
};
