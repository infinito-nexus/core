const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm, gotoOnion } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");

const oidcEnabled    = isServiceEnabled("sso");
const oidcIssuerUrl  = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const erpnextBaseUrl = normalizeBaseUrl(process.env.ERPNEXT_BASE_URL || "");
const adminUsername       = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminEmail          = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL);
const adminPassword       = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const adminNativePassword = decodeDotenvQuotedValue(process.env.ADMIN_NATIVE_PASSWORD);
const biberUsername       = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword       = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const canonicalDomain     = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

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
  await page.fill("input#login_email", username);
  await page.fill("input#login_password", password);
  await Promise.all([
    page.waitForURL((url) => url.toString().includes(canonicalDomain) && !url.toString().includes("/login"), {
      timeout: resolveTimeout(60_000),
    }),
    page.click("button.btn-login, button[type='submit']", { timeout: resolveTimeout(30_000) }).catch(() => page.keyboard.press("Enter")),
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
    canonicalDomain,
  },
  signInViaErpnextOidc,
  signInViaErpnextLocal,
  erpnextLogout,
  beforeEach,
  skipUnlessServiceEnabled,
};
