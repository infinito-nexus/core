const { test, expect } = require("@playwright/test");

const {
  assertCspMetaParity,
  assertCspResponseHeader,
  expectNoCspViolations,
} = require("./personas");

exports.register = function (shared) {
  test("openwebui enforces Content-Security-Policy and exposes canonical domain from applications lookup", async ({
    page,
  }) => {
    const diagnostics = shared.attachDiagnostics(page);

    const response = await page.goto(`${shared.env.openwebuiBaseUrl}/`);
    expect(response, "Expected openwebui landing response").toBeTruthy();
    expect(
      response.status(),
      "Expected openwebui landing response to be successful"
    ).toBeLessThan(400);

    const directives = assertCspResponseHeader(response, "openwebui landing");
    await assertCspMetaParity(page, directives, "openwebui landing");

    const documentUrl = response.url();
    expect(
      documentUrl.includes(shared.env.canonicalDomain),
      `Expected canonical domain "${shared.env.canonicalDomain}" (from applications lookup) to back the openwebui URL`
    ).toBe(true);

    await expectNoCspViolations(page, diagnostics, "openwebui landing");
  });
};
