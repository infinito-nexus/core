const { test, expect } = require("@playwright/test");
const { expectHstsWhenTls, gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("fediwall root is served under canonical domain with TLS", async ({ page }) => {
    const response = await gotoOnion(page, `${shared.env.appBaseUrl}/`);
    expect(response, "Expected fediwall root response").toBeTruthy();
    expect(response.status(), "Expected fediwall root status < 400").toBeLessThan(400);
    expect(
      response.url().includes(shared.env.canonicalDomain),
      `Expected canonical domain "${shared.env.canonicalDomain}" to back the fediwall URL`
    ).toBe(true);
    const headers = response.headers();
    expectHstsWhenTls(headers, shared.env.appBaseUrl, "fediwall");
  });
};
