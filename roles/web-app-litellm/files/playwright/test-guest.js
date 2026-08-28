const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("guest: LiteLLM admin UI reachable behind the proxy, login gate shown", async ({ page }) => {
    const response = await gotoOnion(page, `${shared.env.baseUrl}/ui`);
    expect(response, "Expected a LiteLLM UI response").toBeTruthy();
    expect(response.status(), "Expected LiteLLM UI status to be < 400").toBeLessThan(400);
    expect(
      response.url().includes(shared.env.canonicalDomain),
      `Expected canonical domain "${shared.env.canonicalDomain}" to back the UI URL`,
    ).toBe(true);
    await expect(
      page.locator("input[type=password]"),
      "guest must face the LiteLLM UI login gate, never an authenticated surface",
    ).toHaveCount(1, { timeout: resolveTimeout(30_000) });
  });
};
