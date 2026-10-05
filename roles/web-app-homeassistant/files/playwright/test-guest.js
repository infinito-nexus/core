const { test, expect } = require("@playwright/test");

const { apiGetOnion, gotoOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("guest: Home Assistant onboarding or login surface is reachable", async ({ page }) => {
    const response = await gotoOnion(page, `${shared.env.baseUrl}/`);
    expect(response, "Expected a Home Assistant response").toBeTruthy();
    expect(response.status(), "Expected Home Assistant status to be < 400").toBeLessThan(400);
    expect(
      response.url().includes(shared.env.canonicalDomain),
      `Expected canonical domain "${shared.env.canonicalDomain}" to back the Home Assistant URL`,
    ).toBe(true);
  });

  test("guest: the onboarding wizard is closed and a visitor ends on the sign-in page", async ({ page }) => {
    const steps = await apiGetOnion(page.request, `${shared.env.baseUrl}/api/onboarding`, { failOnStatusCode: false });
    expect(
      steps.status() === 404 || (await steps.json()).every((step) => step.done),
      "every onboarding step must be done, otherwise any visitor can create the owner account",
    ).toBe(true);

    await gotoOnion(page, `${shared.env.baseUrl}/onboarding.html`);
    await expect(page.locator("ha-authorize"), "the closed wizard must hand a visitor over to the sign-in page").toBeVisible({
      timeout: resolveTimeout(60_000),
    });
    await expect(page.locator("onboarding-welcome, onboarding-create-user")).toHaveCount(0);
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
