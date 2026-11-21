const { expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const { brokerAccessJwt } = require("./_appview");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  requireDotenvValue,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
} = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.BLUESKY_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"));
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const adminEmail = requireDotenvValue(process.env.ADMIN_EMAIL, "ADMIN_EMAIL");
const adminHandle = requireDotenvValue(process.env.ADMIN_HANDLE, "ADMIN_HANDLE");
const adminHandleReserved = requireDotenvValue(process.env.ADMIN_HANDLE_RESERVED, "ADMIN_HANDLE_RESERVED");
const pdsBaseUrl = requireDotenvValue(process.env.PDS_BASE_URL, "PDS_BASE_URL");

async function beforeEach({ page }) {
  expect(baseUrl, "BLUESKY_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
}

async function loginThroughBroker(page) {
  expect(adminUsername, "ADMIN_USERNAME must be set when OIDC is enabled").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set when OIDC is enabled").toBeTruthy();
  await loginThroughBrokerAs(page, adminUsername, adminPassword);
}

async function loginThroughBrokerAs(page, username, password) {
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

  await performKeycloakLoginForm(page, username, password);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(90_000),
      message: `expected post-OIDC URL to land on Bluesky outside /oauth2/* (got: ${page.url()})`,
    })
    .toMatch(new RegExp(`^${expectedBaseUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/(?!oauth2/)`));

  await page.waitForLoadState("networkidle", { timeout: resolveTimeout(30_000) }).catch(() => {});
  await expect(
    page.locator("#root"),
    "the handoff must land on the social-app shell bskyweb renders, not on a proxy or broker error document",
  ).toHaveCount(1, { timeout: resolveTimeout(60_000) });
  await brokerAccessJwt(page);
}

module.exports = {
  env: {
    baseUrl,
    oidcIssuerUrl,
    canonicalDomain,
    adminUsername,
    adminPassword,
    adminEmail,
    adminHandle,
    adminHandleReserved,
    pdsBaseUrl,
    biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME || ""),
    biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD || ""),
    biberFullName: decodeDotenvQuotedValue(process.env.BIBER_FULL_NAME || ""),
  },
  skipUnlessServiceEnabled,
  loginThroughBroker,
  loginThroughBrokerAs,
  performKeycloakLoginForm,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
  beforeEach,
};
