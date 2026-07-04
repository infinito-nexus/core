const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("biber: Semaphore OIDC login lands on authenticated surface", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    test.setTimeout(90_000);
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
    expect(shared.env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();

    await shared.signInViaOidc(page, shared.env.biberUsername, shared.env.biberPassword, "biber");

    await expect(page.locator("body")).toContainText(/dashboard|project|task|new project/i, { timeout: 60_000 });

    await shared.logout(page, "biber");
  });
};
