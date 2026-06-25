const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("OIDC: oauth2-proxy redirects unauthenticated visitors through Keycloak (V1)", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    expect(shared.env.adminUsername, "ADMIN_USERNAME must be set when SSO is enabled").toBeTruthy();
    expect(shared.env.adminPassword, "ADMIN_PASSWORD must be set when SSO is enabled").toBeTruthy();
    expect(shared.env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set when SSO is enabled").toBeTruthy();

    await page.context().clearCookies();

    const expectedOidcAuthUrl = `${shared.env.oidcIssuerUrl}/protocol/openid-connect/auth`;
    await page.goto(`${shared.env.n8nBaseUrl}/`);

    await expect
      .poll(() => page.url(), {
        timeout: 60_000,
        message: `expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`
      })
      .toContain(expectedOidcAuthUrl);

    await require("./personas").performKeycloakLoginForm(
      page, shared.env.adminUsername, shared.env.adminPassword
    );

    await expect
      .poll(() => page.url(), {
        timeout: 90_000,
        message: `expected redirect back to n8n at ${shared.env.n8nBaseUrl}`
      })
      .toContain(shared.env.canonicalDomain);

    await expect(page.locator("body")).toBeVisible({ timeout: 60_000 });

    await shared.n8nLogout(page);
  });
};
