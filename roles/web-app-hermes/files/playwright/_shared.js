const { expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const env = {
  baseUrl: normalizeBaseUrl(process.env.HERMES_BASE_URL || ""),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || ""),
  apiServerKey: decodeDotenvQuotedValue(process.env.HERMES_API_SERVER_KEY || ""),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || ""),
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || ""),
  webuiPassword: decodeDotenvQuotedValue(process.env.HERMES_WEBUI_PASSWORD || ""),
};

async function beforeEach() {}

/**
 * Args:
 *   page: Playwright page, with or without a Keycloak session.
 *   path: web UI path to open.
 */
async function openBehindProxy(page, path) {
  skipUnlessServiceEnabled("webui");
  await gotoOnion(page, `${env.baseUrl}${path}`);
  if (!isServiceEnabled("sso") || !(await page.locator("#kc-form-login").isVisible())) return;
  await performKeycloakLoginForm(page, env.adminUsername, env.adminPassword);
  await expect(page.locator("#app-sidebar")).toBeVisible({ timeout: resolveTimeout(60_000) });
  await gotoOnion(page, `${env.baseUrl}${path}`);
}

/**
 * Args:
 *   page: Playwright page, with or without a Keycloak session.
 */
async function openSignIn(page) {
  await openBehindProxy(page, "/login");
  await expect(page.locator(".provider-list")).toBeVisible({ timeout: resolveTimeout(60_000) });
}

/**
 * Args:
 *   page: Playwright page, with or without a Keycloak session.
 *   path: web UI path to land on after the sign-in.
 */
async function signIn(page, path = "/") {
  await openBehindProxy(page, path);
  if (!isServiceEnabled("sso")) {
    const form = page.locator("form.provider-form");
    await form.locator("input[name='username']").fill(env.adminUsername);
    await form.locator("input[name='password']").fill(env.webuiPassword);
    await form.locator("button[type='submit']").click();
  }
  await expect(page.locator("#app-sidebar")).toBeVisible({ timeout: resolveTimeout(60_000) });
}

module.exports = { env, beforeEach, openSignIn, signIn };
