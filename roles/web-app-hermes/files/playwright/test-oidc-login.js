const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const {
  apiGetOnion,
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  gotoOnion,
} = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.HERMES_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

exports.register = function () {
  test("OIDC: oauth2-proxy redirects visitors through Keycloak onto the agent", async ({ page }) => {
    expect(baseUrl, "HERMES_BASE_URL must be set").toBeTruthy();
    expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
    await page.context().clearCookies();

    skipUnlessServiceEnabled("sso");
    expect(adminUsername, "ADMIN_USERNAME must be set when OIDC is enabled").toBeTruthy();
    expect(adminPassword, "ADMIN_PASSWORD must be set when OIDC is enabled").toBeTruthy();
    expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set when OIDC is enabled").toBeTruthy();
    const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
    await gotoOnion(page, `${baseUrl}/`);
    await expect
      .poll(() => page.url(), {
        timeout: resolveTimeout(60_000),
        message: `expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`,
      })
      .toContain(expectedOidcAuthUrl);
    await performKeycloakLoginForm(page, adminUsername, adminPassword);
    await expect
      .poll(() => page.url(), {
        timeout: resolveTimeout(90_000),
        message: `expected redirect back to the Hermes agent at ${baseUrl}`,
      })
      .toContain(canonicalDomain);
    if (isServiceEnabled("webui")) {
      await expect(
        page.locator("form.provider-form, a.provider-btn").first(),
        "Expected the dashboard's own sign-in surface behind the proxy, not a gateway error page",
      ).toBeVisible({ timeout: resolveTimeout(60_000) });
      return;
    }
    const health = await apiGetOnion(page.request, `${baseUrl}/health`, { timeout: resolveTimeout(30_000) });
    expect(health.status(), "Expected the agent behind the proxy to answer, not a gateway error page").toBe(200);
    expect((await health.json()).status, "Expected /health to report an ok status").toBe("ok");
  });
};
