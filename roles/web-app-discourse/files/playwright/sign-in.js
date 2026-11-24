const { expect } = require("@playwright/test");

const {
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  requireDotenvValue,
} = require("./personas");
const { isServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const FORM_MS = 10_000;

function env(name) {
  return decodeDotenvQuotedValue(process.env[name]);
}

function baseUrl() {
  return normalizeBaseUrl(env("DISCOURSE_BASE_URL"));
}

async function signInViaOidc(page, base, username, password) {
  const issuer = normalizeBaseUrl(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"));
  await gotoOnion(page, `${base}/`);
  await page
    .locator("a, button")
    .filter({ hasText: /log\s*in|sign\s*in/i })
    .first()
    .click({ timeout: resolveTimeout(30_000) });
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected redirect to Keycloak OIDC auth (${issuer})`,
    })
    .toContain(`${issuer}/protocol/openid-connect/auth`);
  await performKeycloakLoginForm(page, username, password);
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected redirect back to discourse at ${base}`,
    })
    .toContain(base);
  const currentUserMenu = page.locator(".header-dropdown-toggle.current-user");
  const createAccount = page.locator(".signup-page-cta__signup");
  await expect(
    currentUserMenu.or(createAccount).first(),
    "expected discourse to open the session or the first-login account confirmation",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
  if (await createAccount.isVisible()) {
    await expect(createAccount, "expected the IdP-filled account form to be submittable").toBeEnabled({
      timeout: resolveTimeout(30_000),
    });
    await expect(
      page.locator("#username-validation"),
      "expected discourse to confirm the IdP-filled username as available before the account form is sent",
    ).toHaveClass(/\bgood\b/, { timeout: resolveTimeout(30_000) });
    await createAccount.click();
    await expect(currentUserMenu, "expected the confirmed account to open a session").toBeVisible({
      timeout: resolveTimeout(60_000),
    });
  }
  await gotoOnion(page, `${base}/latest`);
}

async function signInViaLocalLogin(page, base, username, password) {
  await gotoOnion(page, `${base}/login`);
  const name = page.locator("#login-account-name");
  const passwordField = page.locator("#login-account-password");
  await expect(name, `expected the local login form at ${base}/login (enable_local_logins follows login.method.native and login.method.ldap)`).toBeEditable({
    timeout: resolveTimeout(FORM_MS),
  });
  await name.fill(username);
  await expect(passwordField).toBeEditable({ timeout: resolveTimeout(FORM_MS) });
  await passwordField.fill(password);
  await passwordField.press("Enter");
}

/**
 * Args:
 *   page: Playwright page without a Discourse session; ends signed in on /latest.
 *   username: the persona's login name.
 *   password: the persona's password.
 */
async function signInAs(page, username, password) {
  const base = baseUrl();
  if (isServiceEnabled("sso")) {
    await signInViaOidc(page, base, username, password);
  } else {
    await signInViaLocalLogin(page, base, username, password);
  }
  await expect(
    page.locator(".header-dropdown-toggle.current-user"),
    `expected discourse to answer with the signed-in user menu of ${username}`,
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
}

async function signInAsAdmin(page) {
  await signInAs(page, env("ADMIN_USERNAME"), env("ADMIN_PASSWORD"));
}

module.exports = { signInAs, signInAsAdmin };
