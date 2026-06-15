const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { normalizeBaseUrl, decodeDotenvQuotedValue, performKeycloakLoginForm } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.SNIPE_IT_BASE_URL || process.env.APP_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

test.use({ ignoreHTTPSErrors: true });

test("OIDC: oauth2-proxy + Snipe-IT loginViaRemoteUser mint a native session", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "SNIPE_IT_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  await page.context().clearCookies();

  const expectedAuth = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const expectedBase = baseUrl.replace(/\/$/, "");

  await page.goto(`${expectedBase}/login`);
  await expect
    .poll(() => page.url(), { timeout: 60_000, message: `expected redirect to ${expectedAuth}` })
    .toContain(expectedAuth);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect
    .poll(() => page.url(), { timeout: 90_000, message: `expected redirect back to ${expectedBase}` })
    .toContain(expectedBase.replace(/^https?:\/\//, ""));
  await expect(page.locator("body")).toBeVisible({ timeout: 60_000 });

  const sessionCookies = await page.context().cookies(expectedBase);
  expect(
    sessionCookies.some((cookie) => cookie.name === "snipeit_session"),
    "loginViaRemoteUser must mint a native snipeit_session cookie",
  ).toBe(true);

  const profileResponse = await page.request.get(`${expectedBase}/account/profile`, {
    maxRedirects: 0,
  });
  const profileBody = await profileResponse.text();
  expect(
    profileResponse.status(),
    `the auth-only /account/profile must render for the trusted-header session, not 302 back to /login (got ${profileResponse.status()})`,
  ).toBe(200);
  expect(
    profileBody.toLowerCase(),
    "the authenticated profile page must surface the SSO-matched account, not Snipe-IT's login form",
  ).toContain("profile");
});
