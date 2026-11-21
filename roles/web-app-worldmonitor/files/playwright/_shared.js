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
  internalTcpPorts: JSON.parse(decodeDotenvQuotedValue(process.env.INTERNAL_TCP_PORTS_JSON || "[]")),
};

const KEYCLOAK_AUTH_RE = /openid-connect\/auth/;
const API_PROBE_PATH = "/api/sidecar-health";

async function expectKeycloakLogin(page, label) {
  await expect(page, label).toHaveURL(KEYCLOAK_AUTH_RE, { timeout: resolveTimeout(60_000) });
}

async function expectDashboard(page, label) {
  await expect(page.locator("html"), `${label}: the dashboard must finish booting`).toHaveAttribute(
    "data-wm-event-handlers-ready",
    "true",
    { timeout: resolveTimeout(90_000) },
  );
  await expect(page.locator("#mapSection"), `${label}: the map section must be shown`).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  await expect(page.locator("#mapSection canvas").first(), `${label}: the map must draw its canvas`).toBeAttached({
    timeout: resolveTimeout(60_000),
  });
}

async function openApp(page, path) {
  await gotoOnion(page, `${env.appBaseUrl}${path}`, { waitUntil: "domcontentloaded" });
  await assertCspInjections(page, { isEnabled: safeIsEnabled });
}

async function loginToDashboard(page, username, password) {
  await openApp(page, "/");
  if (safeIsEnabled("sso")) {
    await expectKeycloakLogin(page, "an anonymous visit must land on the Keycloak login");
    await performKeycloakLogin(page, username, password, env.canonicalDomain);
  }
  await expectDashboard(page, "after login");
}

async function logout(page) {
  expect(env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set when SSO is enabled").toBeTruthy();
  const keycloakLogout = `${env.oidcIssuerUrl}/protocol/openid-connect/logout`;
  await gotoOnion(page, `${env.appBaseUrl}/oauth2/sign_out?rd=${encodeURIComponent(keycloakLogout)}`, {
    waitUntil: "domcontentloaded",
  });
  const confirm = page.locator("#kc-logout");
  await confirm.waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
  await confirm.click({ timeout: resolveTimeout(30_000) });
  await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) });
  await openApp(page, "/");
  await expectKeycloakLogin(page, "after logout the oauth2 gate must ask Keycloak again");
}

module.exports = {
  env,
  KEYCLOAK_AUTH_RE,
  API_PROBE_PATH,
  expectKeycloakLogin,
  expectDashboard,
  openApp,
  loginToDashboard,
  logout,
};
