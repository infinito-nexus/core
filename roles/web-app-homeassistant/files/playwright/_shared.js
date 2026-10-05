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
 *   page: Playwright page that ends signed in as the owner the deployment provisions.
 */
async function signIn(page) {
  await openSignIn(page);
  const form = page.locator(SIGN_IN_FORM);
  await form.locator('input[name="username"]').fill(env.adminUsername);
  await form.locator('input[name="password"]').fill(env.adminPassword);
  await form.locator('input[name="password"]').press("Enter");
  await expect(page.locator(SHELL)).toBeVisible({ timeout: resolveTimeout(90_000) });
}

async function beforeEach() {}

module.exports = { SHELL, SIGN_IN_FORM, beforeEach, env, openSignIn, signIn };
