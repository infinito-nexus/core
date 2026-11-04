const { expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLoginForm, requireDotenvValue } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const READY_MS = 10_000;
const APP = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const LAM = `${APP}/lam/templates`;
const ADMIN_USERNAME = decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME"));
const ADMIN_PASSWORD = decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD"));
const SSO_ENABLED = process.env.SSO_SERVICE_ENABLED === "true";
const KEYCLOAK = /\/protocol\/openid-connect\//;
const SSO_HOP = /\/protocol\/openid-connect\/|\/login-actions\/|\/oauth2\//;
const SIGNED_IN = '#lam-topnav a.lam-menu-entry[href$="/templates/lists/list.php?type=user"]';
const LOGIN_BUTTON = 'button[name="checklogin"]';
const LOGIN_USERNAME = "input#username";
const LOGIN_PASSWORD = "input#passwd";

async function ready(page, selector) {
  await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(READY_MS) });
}

async function passSsoGate(page) {
  if (!SSO_ENABLED || !KEYCLOAK.test(page.url())) return;
  await performKeycloakLoginForm(page, ADMIN_USERNAME, ADMIN_PASSWORD);
  await page.waitForURL((url) => !SSO_HOP.test(String(url)), {
    timeout: resolveTimeout(60_000),
    waitUntil: "domcontentloaded",
  });
}

async function open(page, path, selector) {
  const url = `${LAM}/${path}`;
  await gotoOnion(page, url);
  if (SSO_ENABLED && KEYCLOAK.test(page.url())) {
    await passSsoGate(page);
    await page.waitForURL((landed) => String(landed).startsWith(`${LAM}/`), {
      timeout: resolveTimeout(60_000),
      waitUntil: "domcontentloaded",
    });
    if (page.url() !== url) await gotoOnion(page, url);
  }
  await ready(page, selector);
}

async function submitLogin(page, username, password) {
  await open(page, "login.php", LOGIN_BUTTON);
  const user = page.locator(LOGIN_USERNAME);
  const secret = page.locator(LOGIN_PASSWORD);
  await expect(user).toBeEditable({ timeout: resolveTimeout(READY_MS) });
  await user.fill(username);
  await expect(secret).toBeEditable({ timeout: resolveTimeout(READY_MS) });
  await secret.fill(password);
  await page.locator(LOGIN_BUTTON).click();
  await page.waitForLoadState("domcontentloaded");
}

async function signIn(page) {
  await submitLogin(page, ADMIN_USERNAME, ADMIN_PASSWORD);
  await expect(page.locator(SIGNED_IN)).toHaveCount(1, { timeout: resolveTimeout(30_000) });
}

async function openSignedIn(page, path, selector) {
  await open(page, path, "body");
  if ((await page.locator(SIGNED_IN).count()) === 0) {
    await signIn(page);
    await gotoOnion(page, `${LAM}/${path}`);
  }
  await ready(page, selector);
}

module.exports = {
  ADMIN_PASSWORD,
  ADMIN_USERNAME,
  APP,
  LAM,
  LOGIN_BUTTON,
  LOGIN_PASSWORD,
  LOGIN_USERNAME,
  READY_MS,
  SIGNED_IN,
  SSO_ENABLED,
  open,
  openSignedIn,
  ready,
  signIn,
  submitLogin,
};
