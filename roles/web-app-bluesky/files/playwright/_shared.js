const { expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
} = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.BLUESKY_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const adminHandle = decodeDotenvQuotedValue(process.env.ADMIN_HANDLE || "");
const pdsBaseUrl = decodeDotenvQuotedValue(process.env.PDS_BASE_URL || "");

async function beforeEach({ page }) {
  expect(baseUrl, "BLUESKY_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
}

async function loginThroughBroker(page) {
  expect(adminUsername, "ADMIN_USERNAME must be set when OIDC is enabled").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set when OIDC is enabled").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set when OIDC is enabled").toBeTruthy();

  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const expectedBaseUrl = baseUrl.replace(/\/$/, "");

  await gotoOnion(page, `${expectedBaseUrl}/`);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`,
    })
    .toContain(expectedOidcAuthUrl);

  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(90_000),
      message: `expected post-OIDC URL to land on Bluesky outside /oauth2/* (got: ${page.url()})`,
    })
    .toMatch(new RegExp(`^${expectedBaseUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/(?!oauth2/)`));

  await page.waitForLoadState("networkidle", { timeout: resolveTimeout(30_000) }).catch(() => {});
  await expect(page.locator("body")).toBeVisible({ timeout: resolveTimeout(60_000) });
}

module.exports = {
  env: {
    baseUrl,
    oidcIssuerUrl,
    canonicalDomain,
    adminUsername,
    adminPassword,
    adminHandle,
    pdsBaseUrl,
  },
  skipUnlessServiceEnabled,
  loginThroughBroker,
  performKeycloakLoginForm,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
  beforeEach,
};
