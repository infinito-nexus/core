const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("kix root emits TLS+HSTS", async ({ page }) => {
    const response = await page.goto(`${shared.env.appBaseUrl}/`);
    expect(response, "Expected a response from the KIX root").toBeTruthy();
    expect(response.status(), "Expected KIX root status < 500").toBeLessThan(500);
    const headers = response.headers();
    expect(headers["strict-transport-security"], "kix must emit HSTS").toBeTruthy();
  });
};
