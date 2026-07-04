const { expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");

const ssoEnabled        = isServiceEnabled("sso");
const ldapEnabled       = isServiceEnabled("ldap");
const oidcIssuerUrl     = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const jellyfinBaseUrl   = normalizeBaseUrl(process.env.JELLYFIN_BASE_URL || "");
const adminUsername     = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminNativePassword = decodeDotenvQuotedValue(process.env.ADMIN_NATIVE_PASSWORD);
const biberUsername     = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword     = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const canonicalDomain   = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

async function gotoLogin(page) {
  await page.goto(`${jellyfinBaseUrl}/web/`, { waitUntil: "domcontentloaded" });
}

function onLoginSurface(page) {
  return /login\.html|\/web\/?($|#\/?$)/.test(page.url());
}

async function assertAuthenticated(page, label) {
  await expect(
    page
      .getByRole("button", { name: "Menu" })
      .or(page.getByRole("button", { name: "Search" }))
      .first(),
    `${label}: authenticated Jellyfin chrome must be visible`,
  ).toBeVisible({ timeout: 60_000 });
}

async function fillManualLogin(page, username, password) {
  const userField = page.locator("#txtManualName, input[name='username'], input[type='text']").first();
  await userField.waitFor({ state: "visible", timeout: 30_000 });
  await userField.fill(username);
  await page.locator("#txtManualPassword, input[type='password']").first().fill(password);
  await page
    .locator("button[type='submit'], .btnSubmit")
    .first()
    .click()
    .catch(() => page.keyboard.press("Enter"));
}

// Jellyfin's manual login form authenticates local users and, when the LDAP
// plugin is active, LDAP users through the same form.
async function signInViaLocal(page, username, password, label) {
  await gotoLogin(page);
  await fillManualLogin(page, username, password);
  await assertAuthenticated(page, label);
}

async function signInViaLdap(page, username, password, label) {
  await signInViaLocal(page, username, password, label);
}

// The SSO plugin renders an extra provider button on the login page.
async function signInViaOidc(page, username, password, label) {
  await gotoLogin(page);
  const oidcButton = page
    .locator("a, button")
    .filter({ hasText: /sign\s*in\s*with|keycloak|single\s*sign|sso|openid/i })
    .first();
  await expect(
    oidcButton,
    `${label}: the SSO provider button must render on the Jellyfin login page`,
  ).toBeVisible({ timeout: 30_000 });
  await oidcButton.click();

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `${label}: expected redirect to Keycloak (${oidcIssuerUrl}/protocol/openid-connect/auth)`,
    })
    .toContain(`${oidcIssuerUrl}/protocol/openid-connect/auth`);

  await performKeycloakLoginForm(page, username, password);
  await assertAuthenticated(page, label);
}

async function logout(page, label = "session") {
  try {
    const menu = page
      .getByRole("button", { name: "Menu" })
      .or(page.locator(".headerUserButton, .mainDrawerButton"))
      .first();
    if (await menu.count()) {
      await menu.click({ timeout: 5_000 }).catch(() => {});
    }
    const signOut = page
      .getByRole("link", { name: /sign\s*out|log\s*out|logout|abmelden/i })
      .or(page.locator("a, button, .listItem").filter({ hasText: /sign\s*out|log\s*out|logout|abmelden/i }))
      .first();
    if (await signOut.count()) {
      await signOut.click({ timeout: 5_000 }).catch(() => {});
      await page.waitForLoadState("domcontentloaded", { timeout: 8_000 }).catch(() => {});
    }
  } catch {
    /* best-effort */
  }

  await page.context().clearCookies();
  await gotoLogin(page).catch(() => {});
  await page
    .evaluate(() => {
      try {
        window.localStorage.clear();
        window.sessionStorage.clear();
      } catch {
        /* noop */
      }
    })
    .catch(() => {});
  await gotoLogin(page);
  await expect
    .poll(() => onLoginSurface(page), {
      timeout: 30_000,
      message: `${label}: expected logged-out landing on the Jellyfin login surface`,
    })
    .toBe(true);
}

async function beforeEach({ page }) {
  await page.setViewportSize({ width: 1440, height: 1100 });
  expect(jellyfinBaseUrl, "JELLYFIN_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
}

module.exports = {
  env: {
    ssoEnabled,
    ldapEnabled,
    oidcIssuerUrl,
    jellyfinBaseUrl,
    adminUsername,
    adminNativePassword,
    biberUsername,
    biberPassword,
    canonicalDomain,
  },
  gotoLogin,
  onLoginSurface,
  assertAuthenticated,
  signInViaLocal,
  signInViaLdap,
  signInViaOidc,
  logout,
  beforeEach,
  skipUnlessServiceEnabled,
};
