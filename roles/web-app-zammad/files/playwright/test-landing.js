const { test, expect } = require("@playwright/test");
const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("zammad landing reachable on canonical domain", async ({ page }) => {
    const response = await gotoOnion(page, `${shared.env.zammadBaseUrl}/`);
    expect(response, "Expected zammad landing response").toBeTruthy();
    expect(response.status(), "Expected zammad landing status to be < 500").toBeLessThan(500);

    const documentUrl = response.url();
    expect(
      documentUrl.includes(shared.env.canonicalDomain),
      `Expected canonical domain "${shared.env.canonicalDomain}" to back the Zammad URL`
    ).toBe(true);
  });
};
