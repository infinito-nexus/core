// Shared KIX Playwright spec state: env vars consumed by more than one
// scenario, the KIX-form login helper, the full OAuth2-proxy → Keycloak →
// KIX-LDAP login/logout flow used by both the administrator and the biber
// login tests, and the `beforeEach` env-presence guard. Per-test env
// (admin credentials, biber credentials, Keycloak admin API access, etc.)
// stays in the respective `test-*.js` file.

const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, performKeycloakLoginForm, runBiberFlow, runGuestFlow, gotoOnion } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");

const ssoEnabled    = isServiceEnabled("sso");
const ldapEnabled   = isServiceEnabled("ldap");

const appBaseUrl      = decodeDotenvQuotedValue(process.env.APP_BASE_URL      || "").replace(/\/$/, "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN  || "");
const oidcIssuerUrl   = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL   || "").replace(/\/$/, "");
const logoutUrl       = decodeDotenvQuotedValue(process.env.LOGOUT_URL        || "").replace(/\/$/, "");

async function performKixLogin(page, username, password) {
  const usernameInput = page.locator('input[type="text"], input[type="email"], input[name="UserLogin"], input[name="username"]').first();
  const passwordInput = page.locator('input[type="password"]').first();
  const submitButton  = page.locator('button[type="submit"], input[type="submit"], button:has-text("Login")').first();

  await usernameInput.waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
  await usernameInput.fill(username);
  await passwordInput.fill(password);
  await submitButton.click({ timeout: resolveTimeout(30_000) });
}

async function runKixLoginLogoutFlow(page, username, password) {
  const expectedAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await gotoOnion(page, `${appBaseUrl}/`, { waitUntil: "domcontentloaded" });

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(30_000),
      message: `Expected redirect to Keycloak OIDC auth: ${expectedAuthUrl}`,
    })
    .toContain(expectedAuthUrl);
  await performKeycloakLoginForm(page, username, password);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `Expected redirect back to canonical KIX URL on ${canonicalDomain}`,
    })
    .toContain(canonicalDomain);

  await page.waitForLoadState("domcontentloaded");
  await performKixLogin(page, username, password);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(30_000),
      message: `Expected SPA to leave /auth after successful LDAP login as ${username}`,
    })
    .not.toContain("/auth");

  await gotoOnion(page, logoutUrl, { waitUntil: "commit" }).catch(() => {});

  await page.context().clearCookies();
  await gotoOnion(page, `${appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(30_000),
      message: `Expected post-logout request to be re-gated to ${expectedAuthUrl}`,
    })
    .toContain(expectedAuthUrl);
}

async function beforeEach({ page }) {
  expect(appBaseUrl,      "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  expect(oidcIssuerUrl,   "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(logoutUrl,       "LOGOUT_URL must be set").toBeTruthy();
  await page.context().clearCookies();
}

module.exports = {
  env: {
    ssoEnabled,
    ldapEnabled,
    appBaseUrl,
    canonicalDomain,
    oidcIssuerUrl,
    logoutUrl,
  },
  performKixLogin,
  runKixLoginLogoutFlow,
  beforeEach,
  isServiceEnabled,
  skipUnlessServiceEnabled,
  runBiberFlow,
  runGuestFlow,
};
