const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("administrator: n8n OIDC login lands on authenticated surface", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    expect(shared.env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
    expect(shared.env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();

    await shared.signInViaN8nOidc(page, shared.env.adminUsername, shared.env.adminPassword, "administrator");

    await expect(page.locator("body")).toContainText(
      /workflow|execution|credential|canvas|overview/i,
      { timeout: 60_000 }
    );

    await shared.n8nLogout(page);
  });
};
