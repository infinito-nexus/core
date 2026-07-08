const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const {
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  gotoOnion,
} = require("../personas");

// plg_system_keycloak is Joomla's native OIDC SSO plugin (in-role plugin,
// configured purely via JOOMLA_OIDC_* env vars injected by templates/env.j2;
// installed + enabled by tasks/07_oidc_plugin.yml). It has no in-app settings
// panel, so its observable coupling surface is the live OIDC handshake:
//   1. The plugin's onAfterInitialise guard redirects an unauthenticated
//      visitor to the *configured* Keycloak issuer (proves issuer/client_id
//      env wiring) — NOT to a generic login page.
//   2. After a real Keycloak credential exchange the browser lands back on
//      Joomla in an AUTHENTICATED session (proves the redirect_uri/client_secret
//      callback completed and the plugin provisioned/logged in the user).
//   3. Re-requesting the guarded root then no longer bounces to Keycloak
//      (proves the session is established, not a redirect loop).
// This asserts the integration end to end and FAILS if the plugin is not
// installed, not enabled, or the OIDC client env is missing/mismatched.
const joomlaBaseUrl = normalizeBaseUrl(process.env.JOOMLA_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

test.use({ ignoreHTTPSErrors: true });

test("addon plg_system_keycloak: OIDC handshake couples Joomla to the configured Keycloak and establishes an authenticated session", async ({ page }) => {
  skipUnlessAddonEnabled("plg_system_keycloak");
  skipUnlessServiceEnabled("sso");

  expect(joomlaBaseUrl, "JOOMLA_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set when OIDC is enabled").toBeTruthy();

  await page.context().clearCookies();

  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const expectedJoomlaBaseUrl = joomlaBaseUrl.replace(/\/$/, "");

  // Step 1: the guard MUST redirect a guest to the CONFIGURED Keycloak issuer.
  await gotoOnion(page, `${expectedJoomlaBaseUrl}/`);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected the plg_system_keycloak guard to redirect to the configured Keycloak OIDC auth endpoint (${expectedOidcAuthUrl})`,
    })
    .toContain(expectedOidcAuthUrl);

  // The redirect must carry THIS Joomla's OIDC client_id, proving the
  // env-injected client (not some default) is what the plugin handed to
  // Keycloak. Keycloak echoes client_id in the auth URL.
  const authUrl = new URL(page.url());
  expect(
    authUrl.searchParams.get("client_id"),
    "Expected the Keycloak auth redirect to carry an OIDC client_id from the injected JOOMLA_OIDC_CLIENT_ID",
  ).toBeTruthy();
  expect(
    authUrl.searchParams.get("redirect_uri") || "",
    "Expected the OIDC redirect_uri to point back at this Joomla instance (proves JOOMLA_OIDC_REDIRECT_URI wiring)",
  ).toContain(new URL(expectedJoomlaBaseUrl).host);

  // Step 2: real Keycloak credential exchange.
  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected the OIDC callback to land back on Joomla at ${expectedJoomlaBaseUrl}`,
    })
    .toContain(expectedJoomlaBaseUrl);

  // Step 3: the callback must have established an authenticated session.
  // Re-request the guarded root: a logged-in session is NOT bounced back to
  // the Keycloak auth endpoint (the guard only redirects guests). A bounce
  // here means the callback failed to provision/log in the user — i.e. the
  // integration is not actually coupled.
  await gotoOnion(page, `${expectedJoomlaBaseUrl}/`);
  await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(60_000) }).catch(() => {});

  expect(
    page.url(),
    "Expected an authenticated Joomla session after the OIDC callback: re-requesting the guarded root must NOT bounce back to the Keycloak auth endpoint",
  ).not.toContain(expectedOidcAuthUrl);
  expect(
    page.url(),
    "Expected to remain on this Joomla instance after the OIDC handshake",
  ).toContain(expectedJoomlaBaseUrl);

  await expect(
    page.locator("body"),
    "Expected the authenticated Joomla front-end to render after the plg_system_keycloak OIDC handshake",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
});
