const { test, expect } = require("@playwright/test");

const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("erpnext landing reachable on canonical domain", async ({ page }) => {
    const response = await gotoOnion(page, `${shared.env.erpnextBaseUrl}/login`);
    expect(response, "Expected ERPNext landing response").toBeTruthy();
    expect(response.status(), "Expected ERPNext login status to be < 500").toBeLessThan(500);

    const documentUrl = response.url();
    expect(
      documentUrl.includes(shared.env.canonicalDomain),
      `Expected canonical domain "${shared.env.canonicalDomain}" to back the ERPNext URL`
    ).toBe(true);
  });
};
