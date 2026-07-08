const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("administrator: n8n SSO auto-provisioning lands directly on the workflow editor (V1)", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    expect(shared.env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
    expect(shared.env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();

    // hooks.js (EXTERNAL_HOOK_FILES) auto-provisions/logs in the user from
    // the trusted Remote-Email header openresty sets once the oauth2-proxy
    // auth_request gate passes, so the Keycloak round-trip lands directly on
    // n8n's authenticated surface — no second, n8n-local sign-in step.
    await shared.signInViaN8nOidc(page, shared.env.adminUsername, shared.env.adminPassword, "administrator");

    await expect(page.locator("body")).toContainText(
      /workflow|execution|credential|canvas|overview/i,
      { timeout: 60_000 }
    );

    await shared.n8nLogout(page);
  });

  test("administrator: n8n local sign-in with owner credentials (V2, no SSO)", async ({ page }) => {
    test.skip(shared.env.oidcEnabled, "SSO shared service enabled — covered by the V1 test above");
    expect(shared.env.adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
    expect(shared.env.n8nOwnerPassword, "N8N_OWNER_PASSWORD must be set").toBeTruthy();

    // No oauth2-proxy edge in V2: n8n presents its native login form
    // directly, and only the owner account (tasks/02_bootstrap.yml) exists.
    await page.goto(`${shared.env.n8nBaseUrl}/`);

    await shared.performN8nLoginForm(page, shared.env.adminEmail, shared.env.n8nOwnerPassword);

    await expect(page.locator("body")).toContainText(
      /workflow|execution|credential|canvas|overview/i,
      { timeout: 60_000 }
    );

    await shared.n8nLogout(page);
  });
};
