const { expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const env = {
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || ""),
  baseUrl: normalizeBaseUrl(process.env.LITELLM_UI_BASE_URL || ""),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || ""),
  uiPassword: decodeDotenvQuotedValue(process.env.LITELLM_UI_PASSWORD || ""),
};

const SIGN_IN_FORM = "form:has(input[type=password])";
const SHELL = "img[alt='LiteLLM Brand']";

/**
 * Args:
 *   page: Playwright page to open the gateway's own username and password form on.
 */
async function openSignIn(page) {
  await gotoOnion(page, `${env.baseUrl}/fallback/login`);
  await expect(page.locator(SIGN_IN_FORM)).toBeVisible({ timeout: resolveTimeout(60_000) });
}

/**
 * Args:
 *   page: Playwright page that ends signed in to the admin UI with the UI credentials the gateway provisions.
 */
async function signIn(page) {
  await openSignIn(page);
  const form = page.locator(SIGN_IN_FORM);
  await form.locator("input[name=username]").fill(env.adminUsername);
  await form.locator("input[name=password]").fill(env.uiPassword);
  await form.locator("input[type=submit]").click();
  await expect(page.locator(SHELL)).toBeVisible({ timeout: resolveTimeout(90_000) });
}

async function beforeEach() {}

module.exports = { SHELL, SIGN_IN_FORM, beforeEach, env, openSignIn, signIn };
