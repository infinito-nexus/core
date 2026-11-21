const { expect, request, test } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm, gotoOnion, requireDotenvValue } = require("./personas");
const { isServiceEnabled, skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");

const oidcEnabled    = isServiceEnabled("sso");
const oidcIssuerUrl  = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const erpnextBaseUrl = normalizeBaseUrl(process.env.ERPNEXT_BASE_URL || "");
const adminUsername       = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminEmail          = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL);
const adminPassword       = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const adminNativePassword = decodeDotenvQuotedValue(process.env.ADMIN_NATIVE_PASSWORD);
const biberUsername       = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword       = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const biberEmail          = requireDotenvValue(process.env.BIBER_EMAIL, "BIBER_EMAIL").toLowerCase();
const managedRoles        = JSON.parse(decodeDotenvQuotedValue(process.env.RBAC_MANAGED_ROLES_JSON || "[]"));
const canonicalDomain     = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);
const adminApiKey         = decodeDotenvQuotedValue(process.env.ADMIN_API_KEY);
const adminApiSecret      = decodeDotenvQuotedValue(process.env.ADMIN_API_SECRET);
const apiBotEnabled       = process.env.API_BOT_ENABLED === "true";
const loginMethods = {
  ldap: process.env.LOGIN_METHOD_LDAP_ENABLED === "true",
  native: process.env.LOGIN_METHOD_NATIVE_ENABLED === "true",
  email: process.env.LOGIN_METHOD_EMAIL_ENABLED === "true",
  registration: process.env.LOGIN_METHOD_REGISTRATION_ENABLED === "true",
  twoFactor: process.env.LOGIN_METHOD_2FA_ENABLED === "true",
};
const localFormShown = loginMethods.native || loginMethods.ldap;

const LOGIN_SECTION = "section.for-login";

/**
 * Returns:
 *   An API request context that authenticates as the API bot through its token, the break-glass path that stays open while disable_user_pass_login refuses every password sign-in; dispose it after use. Skips the calling test while services.erpnext.api_bot.enabled is off, since the deploy then retires the bot and its token.
 */
async function breakGlassApi() {
  test.skip(!apiBotEnabled, "services.erpnext.api_bot.enabled is off, so the site holds no API bot token");
  expect(adminApiKey, "ADMIN_API_KEY must be set").toBeTruthy();
  expect(adminApiSecret, "ADMIN_API_SECRET must be set").toBeTruthy();
  return request.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: { Authorization: `token ${adminApiKey}:${adminApiSecret}` },
  });
}

async function erpnextLogout(page) {
  await gotoOnion(page, `${erpnextBaseUrl}/api/method/logout`, { waitUntil: "commit" }).catch(() => {});
  if (oidcIssuerUrl) {
    await gotoOnion(page, `${oidcIssuerUrl}/protocol/openid-connect/logout`, { waitUntil: "commit" }).catch(() => {});
  }
  await page.context().clearCookies();
}

// Frappe's /login form serves both native local users and LDAP-federated users
// (local DB lookup first, LDAP fallback when LDAP Settings is enabled).
async function signInViaErpnextLocal(page, username, password, personaLabel) {
  await gotoOnion(page, `${erpnextBaseUrl}/login`);
  await expect(page.locator(`${LOGIN_SECTION} input#login_password`)).toBeEditable({
    timeout: resolveTimeout(30_000),
  });
  await page.fill(`${LOGIN_SECTION} input#login_email`, username);
  await page.fill(`${LOGIN_SECTION} input#login_password`, password);
  await Promise.all([
    page.waitForURL((url) => url.toString().includes(canonicalDomain) && !url.toString().includes("/login"), {
      timeout: resolveTimeout(60_000),
    }),
    page
      .click(`${LOGIN_SECTION} button.btn-login, ${LOGIN_SECTION} button[type='submit']`, {
        timeout: resolveTimeout(30_000),
      })
      .catch(() => page.keyboard.press("Enter")),
  ]);
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `${personaLabel}: expected post-login redirect on ${canonicalDomain} (not /login)`,
    })
    .not.toContain("/login");
}

async function signInViaErpnextOidc(page, username, password, personaLabel) {
  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await gotoOnion(page, `${erpnextBaseUrl}/login`);

  const oidcSignIn = page
    .locator("a, button")
    .filter({ hasText: /sso\s*login|sign\s*in\s+with|continue\s+with|single\s+sign[-\s]*on|keycloak|infinito/i })
    .first();

  await expect(
    oidcSignIn,
    `${personaLabel}: the Keycloak SSO button must render on /login (Social Login Key not picked up by the workers?)`,
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
  await oidcSignIn.click({ timeout: resolveTimeout(30_000) });

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `${personaLabel}: expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`,
    })
    .toContain(expectedOidcAuthUrl);

  await performKeycloakLoginForm(page, username, password);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `${personaLabel}: expected redirect back to ERPNext at ${erpnextBaseUrl}`,
    })
    .toContain(canonicalDomain);
}

async function beforeEach({ page }) {
  await page.setViewportSize({ width: 1440, height: 1100 });

  expect(erpnextBaseUrl,  "ERPNEXT_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
}

module.exports = {
  env: {
    oidcEnabled,
    oidcIssuerUrl,
    erpnextBaseUrl,
    adminUsername,
    adminEmail,
    adminPassword,
    adminNativePassword,
    biberUsername,
    biberPassword,
    biberEmail,
    managedRoles,
    canonicalDomain,
    loginMethods,
    localFormShown,
  },
  breakGlassApi,
  signInViaErpnextOidc,
  signInViaErpnextLocal,
  erpnextLogout,
  beforeEach,
  skipUnlessServiceDisabled,
  skipUnlessServiceEnabled,
};
