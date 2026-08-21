const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("administrator: ERPNext OIDC login lands on Frappe desk", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    expect(shared.env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
    expect(shared.env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();

    await shared.signInViaErpnextOidc(page, shared.env.adminUsername, shared.env.adminPassword, "administrator");

    await expect(page.locator("body")).toContainText(/desk|workspace|erpnext|home|dashboard/i, { timeout: resolveTimeout(60_000) });

    await shared.erpnextLogout(page);
  });
};
