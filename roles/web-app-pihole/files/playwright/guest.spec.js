// @ts-check
// Scenario: Unauthenticated guest is redirected to SSO login
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

test.use({ ignoreHTTPSErrors: true });

const oidcIssuerUrl = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const piholeBaseUrl = decodeDotenvQuotedValue(process.env.PIHOLE_BASE_URL);

test.beforeEach(() => {
  skipUnlessServiceEnabled("sso");
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set while the sso service is enabled").toBeTruthy();
  expect(piholeBaseUrl, "PIHOLE_BASE_URL must be set").toBeTruthy();
});

test("guest: is redirected to SSO login", async ({ page }) => {
  const expectedOidcAuthUrl = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;
  await gotoOnion(page, `${piholeBaseUrl.replace(/\/$/, "")}/`);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(30_000), message: "Expected redirect to Keycloak OIDC auth" })
    .toContain(expectedOidcAuthUrl);
});
