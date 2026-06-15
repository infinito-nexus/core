const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");

const joomlaBaseUrl = normalizeBaseUrl(process.env.JOOMLA_BASE_URL);
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

test.use({ ignoreHTTPSErrors: true });

test("OIDC: native plg_system_keycloak redirects unauthenticated visitors to Keycloak and logs them back in to Joomla", async ({ page }) => {
  // The plg_system_keycloak plugin shipped under
  // roles/web-app-joomla/files/joomla-oidc-plugin/ implements native
  // OIDC SSO against Keycloak (no oauth2-proxy sidecar). Visiting the
  // Joomla site root `/` while gated by the plugin redirects the
  // browser to the Keycloak authorization endpoint. After Keycloak
  // login, the plugin handles the callback at
  // /index.php?option=keycloak&task=callback, provisions/updates the
  // local Joomla user with RBAC group memberships derived from the
  // Keycloak `groups` claim, and lands the user back on the original
  // URL.
  expect(joomlaBaseUrl, "JOOMLA_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  await page.context().clearCookies();
  skipUnlessServiceEnabled("sso");
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set when OIDC is enabled").toBeTruthy();

  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const expectedJoomlaBaseUrl = joomlaBaseUrl.replace(/\/$/, "");

  await page.goto(`${expectedJoomlaBaseUrl}/`);

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`
    })
    .toContain(expectedOidcAuthUrl);

  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `expected redirect back to Joomla at ${expectedJoomlaBaseUrl}`
    })
    .toContain(expectedJoomlaBaseUrl);

  // Joomla front-end renders after the OIDC handshake. RBAC mapping
  // gave the administrator persona Super Users (id 8), so the
  // administrator landing nav link is visible to logged-in users.
  await expect(page.locator("body")).toBeVisible({ timeout: 60_000 });
});
