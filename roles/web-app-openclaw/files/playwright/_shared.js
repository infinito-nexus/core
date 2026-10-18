const fs = require("node:fs");

const { expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");
const { isServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const DEVICE_STATE = "/volume/control-ui-device.json";
const DEVICE_KEYS = "^openclaw(-device-identity-|\\.device\\.auth\\.)";
const GATE = ".login-gate";
const SHELL = "openclaw-app-shell";

const env = {
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || ""),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || ""),
  baseUrl: normalizeBaseUrl(process.env.OPENCLAW_BASE_URL || ""),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || ""),
  gatewayToken: decodeDotenvQuotedValue(process.env.OPENCLAW_GATEWAY_TOKEN || ""),
  ssoEnabled: String(process.env.SSO_SERVICE_ENABLED || "").toLowerCase() === "true",
};

async function beforeEach() {}

/**
 * Args:
 *   page: Playwright page, with or without a Keycloak session.
 *   path: Control UI path to open.
 */
async function open(page, path = "/") {
  await gotoOnion(page, `${env.baseUrl}${path}`);
  if (!isServiceEnabled("sso") || !(await page.locator("#kc-form-login").isVisible())) return;
  await performKeycloakLoginForm(page, env.adminUsername, env.adminPassword);
  await expect(page.locator("openclaw-app")).toBeAttached({ timeout: resolveTimeout(60_000) });
  await gotoOnion(page, `${env.baseUrl}${path}`);
}

/**
 * Args:
 *   page: Playwright page whose browser holds no gateway credentials.
 */
async function openGate(page) {
  await open(page);
  await expect(page.locator(GATE)).toBeVisible({ timeout: resolveTimeout(60_000) });
}

/**
 * Args:
 *   page: Playwright page that shows the login gate.
 */
async function submitToken(page) {
  await page.locator(`${GATE} .login-gate__secret-row input`).first().fill(env.gatewayToken);
  await page.locator(`${GATE} .login-gate__connect`).click();
}

/**
 * Args:
 *   page: Playwright page that shows the Control UI.
 *
 * Returns:
 *   true when a device identity paired by an earlier run was put back into the browser.
 */
async function restoreDevice(page) {
  if (!fs.existsSync(DEVICE_STATE)) return false;
  await page.evaluate((entries) => {
    for (const [key, value] of entries) window.localStorage.setItem(key, value);
  }, JSON.parse(fs.readFileSync(DEVICE_STATE, "utf8")));
  return true;
}

async function saveDevice(page) {
  const entries = await page.evaluate(
    (pattern) => Object.entries(window.localStorage).filter(([key]) => new RegExp(pattern).test(key)),
    DEVICE_KEYS,
  );
  fs.writeFileSync(DEVICE_STATE, JSON.stringify(entries), { mode: 0o600 });
}

/**
 * Args:
 *   page: Playwright page, with or without a Keycloak session.
 *   path: Control UI path to land on.
 *   approvalMs: how long an operator has to approve the pairing request of this browser with `openclaw devices approve`.
 *
 * Returns:
 *   true once the gateway admitted this browser, false while its pairing request stays pending.
 */
async function openDashboard(page, path, approvalMs) {
  await open(page, path);
  if (await restoreDevice(page)) await gotoOnion(page, `${env.baseUrl}${path}`);
  const shell = page.locator(SHELL);
  const gate = page.locator(GATE);
  await expect(shell.or(gate).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
  if (await gate.isVisible()) {
    await submitToken(page);
    const admitted = await expect
      .poll(
        async () => {
          if (await shell.isVisible()) return true;
          const connect = gate.locator(".login-gate__connect");
          if (await connect.isVisible()) await connect.click();
          return false;
        },
        { timeout: resolveTimeout(approvalMs), intervals: [5_000] },
      )
      .toBe(true)
      .then(
        () => true,
        () => false,
      );
    if (!admitted) return false;
  }
  await saveDevice(page);
  return true;
}

module.exports = { env, beforeEach, open, openDashboard, openGate, submitToken, GATE };
