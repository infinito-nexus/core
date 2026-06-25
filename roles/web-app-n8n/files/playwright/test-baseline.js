const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("n8n landing reachable on canonical domain", async ({ page }) => {
    const response = await page.goto(`${shared.env.n8nBaseUrl}/`);
    expect(response, "Expected n8n landing response").toBeTruthy();
    expect(response.status(), "Expected n8n landing status to be < 500").toBeLessThan(500);

    const documentUrl = response.url();
    expect(
      documentUrl.includes(shared.env.canonicalDomain),
      `Expected canonical domain "${shared.env.canonicalDomain}" to back the n8n URL`
    ).toBe(true);
  });
};
