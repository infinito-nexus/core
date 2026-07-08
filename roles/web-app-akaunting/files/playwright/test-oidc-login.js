const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");

const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm, gotoOnion } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const baseUrl = normalizeBaseUrl(process.env.AKAUNTING_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

test("OIDC: oauth2-proxy redirects unauthenticated visitors through Keycloak (variant 0)", async ({ page }) => {
  expect(baseUrl, "AKAUNTING_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();

  skipUnlessServiceEnabled("sso");
  expect(adminUsername).toBeTruthy(); expect(adminPassword).toBeTruthy(); expect(oidcIssuerUrl).toBeTruthy();
  const expectedAuth = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const expectedBase = baseUrl.replace(/\/$/, "");
  await gotoOnion(page, `${expectedBase}/`);
  await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).toContain(expectedAuth);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect.poll(() => page.url(), { timeout: resolveTimeout(90_000) }).toContain(expectedBase);
  await expect(page.locator("body")).toBeVisible({ timeout: resolveTimeout(60_000) });
});
