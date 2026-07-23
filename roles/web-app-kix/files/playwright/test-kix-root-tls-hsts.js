const { test, expect } = require("@playwright/test");
const { expectHstsWhenTls, gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("kix root emits TLS+HSTS", async ({ page }) => {
    const response = await gotoOnion(page, `${shared.env.appBaseUrl}/`);
    expect(response, "Expected a response from the KIX root").toBeTruthy();
    expect(response.status(), "Expected KIX root status < 500").toBeLessThan(500);
    const headers = response.headers();
    expectHstsWhenTls(headers, shared.env.appBaseUrl, "kix");
  });
};
