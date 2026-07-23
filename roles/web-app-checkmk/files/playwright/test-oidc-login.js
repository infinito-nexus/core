const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.CHECKMK_BASE_URL || process.env.APP_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

test.use({ ignoreHTTPSErrors: true });

test("OIDC: oauth2-proxy gate + X-Remote-User header establish a real Checkmk session", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000)); // oauth2-proxy + Keycloak round-trip
  expect(baseUrl, "CHECKMK_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  await page.context().clearCookies();

  const expectedAuth = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const expectedBase = baseUrl.replace(/\/$/, "");

  await gotoOnion(page, `${expectedBase}/`);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: `expected redirect to ${expectedAuth}` })
    .toContain(expectedAuth);

  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(90_000), message: `expected redirect back to ${expectedBase}` })
    .toContain(expectedBase.replace(/^https?:\/\//, ""));
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "expected to leave the Checkmk login page" })
    .not.toContain("login.py");
  await expect(page.locator("body")).toContainText(/checkmk|dashboard|monitor|overview/i, { timeout: resolveTimeout(60_000) });
});
