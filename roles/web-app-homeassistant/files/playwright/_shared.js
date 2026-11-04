const { expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const env = {
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || ""),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || ""),
  baseUrl: normalizeBaseUrl(process.env.HOMEASSISTANT_BASE_URL || ""),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || ""),
  mcpEnabled: String(process.env.MCP_SERVICE_ENABLED || "").toLowerCase() === "true",
};

const SIGN_IN_FORM = "ha-authorize ha-auth-flow form";
const SIGN_IN_ERROR = "ha-authorize ha-alert";
const PROVIDER_CHOICE = "ha-authorize ha-pick-auth-provider ha-list-item";
const LOG_OUT_DIALOG = "dialog-box";
const SHELL = "home-assistant-main";

/**
 * Args:
 *   page: Playwright page to open the sign-in form of the hub on.
 */
async function openSignIn(page) {
  await gotoOnion(page, `${env.baseUrl}/`);
  await expect(page.locator(SIGN_IN_FORM)).toBeVisible({ timeout: resolveTimeout(60_000) });
}

/**
 * Args:
 *   page: Playwright page whose shown sign-in form receives the credentials.
 *   username: login name to type.
 *   password: password to type.
 */
async function submitSignIn(page, username, password) {
  const form = page.locator(SIGN_IN_FORM);
  await form.locator('input[name="username"]').fill(username);
  await form.locator('input[name="password"]').fill(password);
  await form.locator('input[name="password"]').press("Enter");
}

/**
 * Args:
 *   page: Playwright page that ends signed in as the owner the deployment provisions.
 */
async function signIn(page) {
  await openSignIn(page);
  await submitSignIn(page, env.adminUsername, env.adminPassword);
  await expect(page.locator(SHELL)).toBeVisible({ timeout: resolveTimeout(90_000) });
}

/**
 * Args:
 *   page: Playwright page that submits credentials to a non-default auth provider of the hub.
 *   providerName: name the sign-in page lists the provider under.
 *   username: login name to type.
 *   password: password to type.
 */
async function signInWithProvider(page, providerName, username, password) {
  await openSignIn(page);
  const choice = page.locator(PROVIDER_CHOICE, { hasText: providerName });
  await choice.click();
  await expect(choice, `picking ${providerName} must replace the local sign-in form`).toHaveCount(0);
  await submitSignIn(page, username, password);
}

/**
 * Args:
 *   page: Playwright page that shows the signed-in interface.
 *
 * Returns:
 *   The id, admin flag and owner flag of the signed-in account.
 */
async function currentUser(page) {
  await expect(page.locator(SHELL)).toBeVisible({ timeout: resolveTimeout(90_000) });
  await expect
    .poll(() => page.evaluate(() => Boolean(document.querySelector("home-assistant")?.hass?.user)), {
      message: "the signed-in interface must know its account",
      timeout: resolveTimeout(30_000),
    })
    .toBe(true);
  return page.evaluate(() => {
    const { id, is_admin: isAdmin, is_owner: isOwner } = document.querySelector("home-assistant").hass.user;
    return { id, isAdmin, isOwner };
  });
}

/**
 * Args:
 *   page: Playwright page that shows the signed-in interface and ends on the sign-in page.
 */
async function signOut(page) {
  await gotoOnion(page, `${env.baseUrl}/profile/general`);
  await page.getByRole("button", { name: /^log out$/i }).first().click();
  await page.locator(LOG_OUT_DIALOG).getByRole("button", { name: /^log out$/i }).click();
  await expect(page.locator(SIGN_IN_FORM)).toBeVisible({ timeout: resolveTimeout(60_000) });
}

/**
 * Args:
 *   browser: Playwright browser the owner signs in with in a context of its own.
 *   userId: id of the account the owner deletes.
 */
async function removeAccount(browser, userId) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await context.newPage();
    await signIn(page);
    await page.evaluate(
      (id) => document.querySelector("home-assistant").hass.callWS({ type: "config/auth/delete", user_id: id }),
      userId,
    );
  } finally {
    await context.close();
  }
}

async function beforeEach() {}

module.exports = {
  SHELL,
  SIGN_IN_ERROR,
  SIGN_IN_FORM,
  beforeEach,
  currentUser,
  env,
  openSignIn,
  removeAccount,
  signIn,
  signInWithProvider,
  signOut,
};
