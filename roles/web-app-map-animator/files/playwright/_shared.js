const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  gotoOnion,
  safeIsEnabled,
  performKeycloakLogin,
  assertCspInjections,
} = require("./personas");

const env = {
  appBaseUrl: normalizeBaseUrl(process.env.APP_BASE_URL || ""),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || ""),
  oidcIssuerUrl: normalizeBaseUrl(process.env.OIDC_ISSUER_URL || ""),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME || ""),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD || ""),
};

const RENDERS_PATH = "/renders/";
const KEYCLOAK_AUTH_RE = /openid-connect\/auth/;
const LOGIN_FORM_RE = /\/renders\/login\?next=/;

async function expectAuthWall(page, label) {
  await expect(page, label).toHaveURL(safeIsEnabled("sso") ? KEYCLOAK_AUTH_RE : LOGIN_FORM_RE, {
    timeout: resolveTimeout(60_000),
  });
}

async function openApp(page) {
  await gotoOnion(page, `${env.appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  await expectAuthWall(page, "an anonymous visit must land on the login");
}

async function gotoRenders(page) {
  await gotoOnion(page, `${env.appBaseUrl}${RENDERS_PATH}`, { waitUntil: "domcontentloaded" });
}

async function nativeLogin(page, username, password) {
  await expect(page, "the render server must ask for its own login").toHaveURL(LOGIN_FORM_RE, {
    timeout: resolveTimeout(60_000),
  });
  const form = page.locator("form[action='/renders/login']");
  await form.getByLabel("User").fill(username);
  await form.getByLabel("Password").fill(password);
  await form.getByRole("button", { name: "Log in" }).click({ timeout: resolveTimeout(30_000) });
  await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) });
}

async function loginToApp(page, username, password) {
  await openApp(page);
  if (safeIsEnabled("sso")) {
    await performKeycloakLogin(page, username, password, env.canonicalDomain);
  }
  await nativeLogin(page, username, password);
  await expect(page, "the login must return to the editor").toHaveURL(`${env.appBaseUrl}/`, {
    timeout: resolveTimeout(30_000),
  });
  await assertCspInjections(page, { isEnabled: safeIsEnabled });
}

async function endSsoSession(page) {
  expect(env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set when SSO is enabled").toBeTruthy();
  const keycloakLogout = `${env.oidcIssuerUrl}/protocol/openid-connect/logout`;
  await gotoOnion(page, `${env.appBaseUrl}/oauth2/sign_out?rd=${encodeURIComponent(keycloakLogout)}`, {
    waitUntil: "domcontentloaded",
  });
  const confirm = page.locator("#kc-logout");
  await confirm.waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
  await confirm.click({ timeout: resolveTimeout(30_000) });
  await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) });
}

async function logout(page) {
  await gotoRenders(page);
  await page.getByRole("button", { name: "Log out" }).click({ timeout: resolveTimeout(30_000) });
  await expect(page, "logout must return to the login form").toHaveURL(/\/renders\/login(\?next=[^&]*)?$/, {
    timeout: resolveTimeout(30_000),
  });
  await gotoRenders(page);
  await expect(page, "after logout the renders must ask for a login again").toHaveURL(LOGIN_FORM_RE, {
    timeout: resolveTimeout(30_000),
  });
  if (safeIsEnabled("sso")) {
    await endSsoSession(page);
    await gotoRenders(page);
    await expectAuthWall(page, "after the SSO logout the oauth2 gate must ask Keycloak again");
  }
}

module.exports = {
  env,
  RENDERS_PATH,
  KEYCLOAK_AUTH_RE,
  LOGIN_FORM_RE,
  openApp,
  gotoRenders,
  nativeLogin,
  loginToApp,
  logout,
};
