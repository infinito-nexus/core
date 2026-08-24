const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("biber: ERPNext OIDC login lands on authenticated surface", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
    expect(shared.env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();

    await shared.signInViaErpnextOidc(page, shared.env.biberUsername, shared.env.biberPassword, "biber");

    await expect(page.locator("body")).toContainText(/desk|workspace|erpnext|home|dashboard|portal/i, { timeout: resolveTimeout(60_000) });

    await shared.erpnextLogout(page);
  });
};
