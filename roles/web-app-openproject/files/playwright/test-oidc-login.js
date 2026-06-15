const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.OPENPROJECT_BASE_URL || process.env.APP_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

test.use({ ignoreHTTPSErrors: true });

test("OIDC: oauth2-proxy + trusted-header bridge establish a real OpenProject session", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "OPENPROJECT_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  await page.context().clearCookies();

  const expectedAuth = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const expectedBase = baseUrl.replace(/\/$/, "");
  await page.goto(`${expectedBase}/`);
  await expect
    .poll(() => page.url(), { timeout: 60_000, message: `expected redirect to ${expectedAuth}` })
    .toContain(expectedAuth);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect
    .poll(() => page.url(), { timeout: 90_000, message: `expected redirect back to ${expectedBase}` })
    .toContain(expectedBase);
  await expect(page.locator("body")).toBeVisible({ timeout: 60_000 });

  const meResponse = await page.request.get(`${expectedBase}/api/v3/users/me`, {
    headers: { Accept: "application/hal+json" },
  });
  const meBody = await meResponse.text();
  expect(
    meResponse.ok(),
    `the trusted-header bridge must authenticate the OpenProject session, got ${meResponse.status()}: ${meBody.slice(0, 300)}`,
  ).toBe(true);

  const me = JSON.parse(meBody);
  expect(me._type, `/api/v3/users/me must resolve to a real User (got ${me._type})`).toBe("User");
  const resolvedLogin = String(me.login || "").toLowerCase();
  expect(
    resolvedLogin,
    `the SSO header login must map to the Keycloak preferred_username (resolved login: ${resolvedLogin})`,
  ).toBe(adminUsername.toLowerCase());

  const projectsResponse = await page.request.get(`${expectedBase}/api/v3/projects`, {
    headers: { Accept: "application/hal+json" },
  });
  expect(
    projectsResponse.ok(),
    `the authenticated session must reach the project collection, got ${projectsResponse.status()}`,
  ).toBe(true);
});
