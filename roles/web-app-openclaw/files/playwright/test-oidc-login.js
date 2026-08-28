const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  gotoOnion,
} = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.OPENCLAW_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

test.use({ ignoreHTTPSErrors: true });

test("OIDC: oauth2-proxy redirects visitors through Keycloak onto the gateway", async ({ page }) => {
  expect(baseUrl, "OPENCLAW_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();

  skipUnlessServiceEnabled("sso");
  expect(adminUsername, "ADMIN_USERNAME must be set when OIDC is enabled").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set when OIDC is enabled").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set when OIDC is enabled").toBeTruthy();
  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  await gotoOnion(page, `${baseUrl}/`);
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
      message: `expected redirect back to the OpenClaw gateway at ${baseUrl}`,
    })
    .toContain(canonicalDomain);
  await expect(page.locator("body")).toBeVisible({ timeout: resolveTimeout(60_000) });
});
