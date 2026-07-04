const { expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");

const oidcEnabled         = isServiceEnabled("sso");
const ldapEnabled         = isServiceEnabled("ldap");
const oidcIssuerUrl       = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const semaphoreBaseUrl    = normalizeBaseUrl(process.env.SEMAPHORE_BASE_URL || "");
const adminUsername       = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword       = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const breakglassUsername  = decodeDotenvQuotedValue(process.env.BREAKGLASS_USERNAME);
const breakglassPassword  = decodeDotenvQuotedValue(process.env.BREAKGLASS_PASSWORD);
const biberUsername       = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword       = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const canonicalDomain     = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

const LOGIN_PATH = "/auth/login";

function onLoginPage(page) {
  return page.url().includes(LOGIN_PATH);
}

async function gotoLogin(page) {
  await page.goto(`${semaphoreBaseUrl}${LOGIN_PATH}`, { waitUntil: "domcontentloaded" });
}

async function assertAuthenticated(page, label) {
  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `${label}: expected to leave the Semaphore login page`,
    })
    .not.toContain(LOGIN_PATH);
  await expect(
    page.locator("header, nav, .v-navigation-drawer, .v-app-bar").first(),
    `${label}: authenticated Semaphore chrome must be visible`,
  ).toBeVisible({ timeout: 60_000 });
}

async function fillLocalLogin(page, username, password) {
  const userField = page.locator("#auth-username").first();
  await userField.waitFor({ state: "visible", timeout: 30_000 });
  await userField.fill(username);
  await page.locator("#auth-password").first().fill(password);
  await page
    .locator('[data-testid="auth-signin"]')
    .first()
    .click()
    .catch(() => page.keyboard.press("Enter"));
}

async function signInViaLocal(page, username, password, label) {
  await gotoLogin(page);
  await fillLocalLogin(page, username, password);
  await assertAuthenticated(page, label);
}

async function signInViaLdap(page, username, password, label) {
  await signInViaLocal(page, username, password, label);
}

async function signInViaOidc(page, username, password, label) {
  await gotoLogin(page);

  const oidcButton = page
    .locator("a, button")
    .filter({ hasText: /sign\s*in\s*with|keycloak|single\s*sign|sso/i })
    .first();
  await expect(
    oidcButton,
    `${label}: the "Sign in with Keycloak" button must render on the Semaphore login page`,
  ).toBeVisible({ timeout: 30_000 });
  await oidcButton.click();

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `${label}: expected redirect to Keycloak OIDC auth (${oidcIssuerUrl}/protocol/openid-connect/auth)`,
    })
    .toContain(`${oidcIssuerUrl}/protocol/openid-connect/auth`);

  await performKeycloakLoginForm(page, username, password);
  await assertAuthenticated(page, label);
}

async function openAccountMenu(page) {
  const trigger = page
    .locator(
      'header button:has(.mdi-account), header button:has(.mdi-account-circle), header .v-avatar, button[aria-label*="account" i], header [role="button"]:has(.mdi-account)',
    )
    .first();
  if (await trigger.count()) {
    await trigger.click().catch(() => {});
  }
}

async function logout(page, label = "session") {
  await openAccountMenu(page);
  const signOut = page
    .locator('a, button, .v-list-item, [role="menuitem"]')
    .filter({ hasText: /sign\s*out|log\s*out|logout|abmelden/i })
    .first();
  if (await signOut.count()) {
    await signOut.click().catch(() => {});
  }
  await page.waitForTimeout(1500);
  if (!onLoginPage(page)) {
    await page.context().clearCookies();
    await gotoLogin(page);
  }
  await expect
    .poll(() => page.url(), {
      timeout: 30_000,
      message: `${label}: expected logged-out landing on the Semaphore login page`,
    })
    .toContain(LOGIN_PATH);
}

async function beforeEach({ page }) {
  await page.setViewportSize({ width: 1440, height: 1100 });
  expect(semaphoreBaseUrl, "SEMAPHORE_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
}

module.exports = {
  env: {
    oidcEnabled,
    ldapEnabled,
    oidcIssuerUrl,
    semaphoreBaseUrl,
    adminUsername,
    adminPassword,
    breakglassUsername,
    breakglassPassword,
    biberUsername,
    biberPassword,
    canonicalDomain,
  },
  LOGIN_PATH,
  gotoLogin,
  onLoginPage,
  assertAuthenticated,
  signInViaLocal,
  signInViaLdap,
  signInViaOidc,
  logout,
  beforeEach,
  skipUnlessServiceEnabled,
};
