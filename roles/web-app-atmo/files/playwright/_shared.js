const { expect } = require("@playwright/test");

const {
  normalizeBaseUrl,
  requireDotenvValue,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
} = require("./personas");

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");

async function beforeEach({ page }) {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
}

module.exports = {
  env: {
    appBaseUrl,
    canonicalDomain,
  },
  beforeEach,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
};
