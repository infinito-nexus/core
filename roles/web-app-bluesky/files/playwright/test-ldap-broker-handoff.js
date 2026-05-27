const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("LDAP: same broker handoff continues to work when Keycloak federates user storage from LDAP", async ({ page }) => {
    // The LDAP variant rides the same login-broker; the only change is
    // Keycloak's user storage backend (LDAP federation against
    // svc-db-openldap). Functionally indistinguishable from the OIDC
    // variant on the Bluesky side, so the scenario asserts the same
    // end state.
    shared.skipUnlessServiceEnabled("ldap");
    shared.skipUnlessServiceEnabled("oidc");
    const { baseUrl, adminUsername, adminPassword } = shared.env;
    expect(adminUsername, "ADMIN_USERNAME must be set when LDAP is enabled").toBeTruthy();
    expect(adminPassword, "ADMIN_PASSWORD must be set when LDAP is enabled").toBeTruthy();
    const expectedBaseUrl = baseUrl.replace(/\/$/, "");

    await page.goto(`${expectedBaseUrl}/`);
    await shared.performKeycloakLoginForm(page, adminUsername, adminPassword);

    await expect
      .poll(() => page.url(), {
        timeout: 90_000,
        message: `expected redirect back to Bluesky web UI at ${expectedBaseUrl}`,
      })
      .toContain(expectedBaseUrl);

    await expect(page.locator("body")).toBeVisible({ timeout: 60_000 });
  });
};
