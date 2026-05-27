const { test, expect } = require("@playwright/test");

const {
  assertCspMetaParity,
  assertCspResponseHeader,
  expectNoCspViolations,
} = require("./personas");

// Baseline scenarios MUST NOT gate on any service.
exports.register = function (shared) {
  test("wordpress front page enforces Content-Security-Policy and renders canonical domain", async ({
    page,
  }) => {
    const diagnostics = shared.attachDiagnostics(page);
    const response = await page.goto(`${shared.env.wpBaseUrl}/`);
    expect(response, "Expected WordPress front page response").toBeTruthy();
    expect(
      response.status(),
      "Expected WordPress front page response to be successful"
    ).toBeLessThan(400);
    const directives = assertCspResponseHeader(response, "wordpress front page");
    await assertCspMetaParity(page, directives, "wordpress front page");
    const html = await response.text();
    expect(
      html.includes(shared.env.canonicalDomain) ||
        (await page.content()).includes(shared.env.canonicalDomain),
      `Expected canonical domain "${shared.env.canonicalDomain}" (from applications lookup) to appear in the WordPress UI`
    ).toBe(true);
    await expectNoCspViolations(page, diagnostics, "wordpress front page");
  });
};
