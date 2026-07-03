const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("administrator: n8n OIDC + local sign-in lands on authenticated surface", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    expect(shared.env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
    expect(shared.env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
    expect(shared.env.adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
    expect(shared.env.n8nOwnerPassword, "N8N_OWNER_PASSWORD must be set").toBeTruthy();

    // The Keycloak round-trip only clears the oauth2-proxy edge gate. n8n
    // Community Edition does not accept that session as its own, so the
    // browser lands on n8n's native login form, not the workflow editor.
    await shared.signInViaN8nOidc(page, shared.env.adminUsername, shared.env.adminPassword, "administrator");

    const emailInput = page.locator('input[type="email"], input[name="email"]').first();
    await expect(emailInput, "expected n8n's own login form after the Keycloak redirect").toBeVisible(
      { timeout: 60_000 }
    );

    await shared.performN8nLoginForm(page, shared.env.adminEmail, shared.env.n8nOwnerPassword);

    await expect(page.locator("body")).toContainText(
      /workflow|execution|credential|canvas|overview/i,
      { timeout: 60_000 }
    );

    await shared.n8nLogout(page);
  });
};
