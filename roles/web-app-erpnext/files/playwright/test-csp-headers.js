const { test, expect } = require("@playwright/test");

const { assertCspMetaParity, assertCspResponseHeader, gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("erpnext login serves Content-Security-Policy headers", async ({ page }) => {
    const response = await gotoOnion(page, `${shared.env.erpnextBaseUrl}/login`);
    expect(response, "Expected ERPNext login response").toBeTruthy();
    expect(response.status(), "Expected ERPNext login status to be < 400").toBeLessThan(400);

    const directives = assertCspResponseHeader(response, "erpnext login");
    await assertCspMetaParity(page, directives, "erpnext login");
  });
};
