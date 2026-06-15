const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.BASEROW_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

test.use({ ignoreHTTPSErrors: true });

test("OIDC: oauth2-proxy + trusted-header bridge mint a Baserow JWT session", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "BASEROW_BASE_URL must be set").toBeTruthy();
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

  const tokenResponse = await page.request.get(`${expectedBase}/api/infinito/sso/token/`);
  const tokenBody = await tokenResponse.text();
  expect(
    tokenResponse.ok(),
    `trusted-header endpoint must return Baserow tokens, got ${tokenResponse.status()}: ${tokenBody}`,
  ).toBe(true);
  const tokenData = JSON.parse(tokenBody);
  expect(tokenData.access_token, "Baserow access token must be present").toBeTruthy();
  expect(tokenData.refresh_token, "Baserow refresh token must be present").toBeTruthy();
  expect(tokenData.user?.email || tokenData.user?.username, "Baserow user data must be present").toBeTruthy();

  const workspacesResponse = await page.request.get(`${expectedBase}/api/workspaces/`, {
    headers: { Authorization: `JWT ${tokenData.access_token}` },
  });
  const workspacesBody = await workspacesResponse.text();
  expect(
    workspacesResponse.ok(),
    `Baserow JWT must authorize workspace listing, got ${workspacesResponse.status()}: ${workspacesBody}`,
  ).toBe(true);
  expect(JSON.parse(workspacesBody).length, "SSO login must provision at least one workspace").toBeGreaterThan(0);
});
