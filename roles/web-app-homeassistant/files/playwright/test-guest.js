const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("guest: Home Assistant onboarding or login surface is reachable", async ({ page }) => {
    const response = await page.goto(`${shared.env.baseUrl}/`);
    expect(response, "Expected a Home Assistant response").toBeTruthy();
    expect(response.status(), "Expected Home Assistant status to be < 400").toBeLessThan(400);
    expect(
      response.url().includes(shared.env.canonicalDomain),
      `Expected canonical domain "${shared.env.canonicalDomain}" to back the Home Assistant URL`,
    ).toBe(true);
  });

  test("guest: the MCP endpoint rejects unauthenticated access", async ({ page }) => {
    test.skip(!shared.env.mcpEnabled, "MCP server integration is disabled in this variant");

    const response = await page.request.get(`${shared.env.baseUrl}/api/mcp`, {
      failOnStatusCode: false,
    });
    expect(
      response.status(),
      "an unauthenticated MCP probe must not be served a 2xx; the endpoint is token-guarded",
    ).toBeGreaterThanOrEqual(400);
  });
};
