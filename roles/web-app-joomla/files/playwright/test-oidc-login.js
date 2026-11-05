const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm, gotoOnion } = require("./personas");

const joomlaBaseUrl = normalizeBaseUrl(process.env.JOOMLA_BASE_URL);
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

test.use({ ignoreHTTPSErrors: true });

test("OIDC: native plg_system_keycloak redirects unauthenticated visitors to Keycloak and logs them back in to Joomla", async ({ page }) => {
  expect(joomlaBaseUrl, "JOOMLA_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  await page.context().clearCookies();
  skipUnlessServiceEnabled("sso");
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set when OIDC is enabled").toBeTruthy();

  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const expectedJoomlaBaseUrl = joomlaBaseUrl.replace(/\/$/, "");

  await gotoOnion(page, `${expectedJoomlaBaseUrl}/`);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`
    })
    .toContain(expectedOidcAuthUrl);

  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected redirect back to Joomla at ${expectedJoomlaBaseUrl}`
    })
    .toContain(expectedJoomlaBaseUrl);

  await expect(
    page.locator("header.container-header"),
    "Expected the Joomla front-end template to render after the handshake, not a gateway error page",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });

  await gotoOnion(page, `${expectedJoomlaBaseUrl}/index.php?option=com_users&view=profile`);

  await expect(
    page.locator("main .com-users-profile, main .com-users-logout").first(),
    "Expected an authenticated Joomla session after the handshake: com_users renders the profile only for a logged-in user and answers a guest with the 404 error template, so the plugin's `index.php?fallback=local` SSO-error page cannot satisfy this",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
});
