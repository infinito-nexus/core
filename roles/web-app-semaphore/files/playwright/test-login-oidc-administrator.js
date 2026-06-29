const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("administrator: Semaphore OIDC login reaches the admin Users surface", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    test.setTimeout(90_000); // OIDC round-trip via Keycloak
    expect(shared.env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
    expect(shared.env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();

    await shared.signInViaOidc(page, shared.env.adminUsername, shared.env.adminPassword, "administrator");

    // Admin-only interaction: the global Users management surface is admin-gated;
    // the OIDC administrator matches the seeded admin by email and must reach it.
    await page.goto(`${shared.env.semaphoreBaseUrl}/users`, { waitUntil: "domcontentloaded" });
    await expect(page, "administrator must not be bounced to login on /users").not.toHaveURL(/\/auth\/login/);
    await expect(page.locator("body")).toContainText(/users|new user|admin/i, { timeout: 60_000 });

    await shared.logout(page, "administrator");
  });
};
