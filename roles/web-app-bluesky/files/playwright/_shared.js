const { expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
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
  performKeycloakLoginForm,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
  beforeEach,
};
