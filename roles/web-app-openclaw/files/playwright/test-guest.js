const { test, expect } = require("@playwright/test");

const { assertCspResponseHeader, assertCspMetaParity } = require("./personas");

exports.register = function (shared) {
  test("guest: OpenClaw dashboard reachable, serves CSP, never exposes an authenticated surface", async ({ page }) => {
    const response = await page.goto(`${shared.env.baseUrl}/`);
    expect(response, "Expected a OpenClaw dashboard response").toBeTruthy();
    expect(response.status(), "Expected OpenClaw status to be < 400").toBeLessThan(400);
    expect(
      response.url().includes(shared.env.canonicalDomain),
      `Expected canonical domain "${shared.env.canonicalDomain}" to back the OpenClaw URL`,
    ).toBe(true);

    const directives = assertCspResponseHeader(response, "openclaw dashboard");
    await assertCspMetaParity(page, directives, "openclaw dashboard");
  });
};
