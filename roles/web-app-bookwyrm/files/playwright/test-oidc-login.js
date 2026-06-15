const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { normalizeBaseUrl, decodeDotenvQuotedValue, performKeycloakLoginForm } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.BOOKWYRM_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

test.use({ ignoreHTTPSErrors: true });

test("OIDC: oauth2-proxy + trusted-header SSO sign the visitor into BookWyrm (variant 0)", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(adminUsername).toBeTruthy();
  expect(adminPassword).toBeTruthy();
  expect(oidcIssuerUrl).toBeTruthy();
  await page.context().clearCookies();

  const expectedAuth = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const expectedBase = baseUrl.replace(/\/$/, "");
  await page.goto(`${expectedBase}/`);
  await expect.poll(() => page.url(), { timeout: 60_000 }).toContain(expectedAuth);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect.poll(() => page.url(), { timeout: 90_000 }).toContain(expectedBase);
  await expect(page.locator("body")).toBeVisible({ timeout: 60_000 });

  await page.goto(`${expectedBase}/preferences/profile`, { waitUntil: "domcontentloaded" });
  await expect(
    page.locator('form[name="edit-profile"]'),
    "trusted-header SSO must sign the visitor into a real BookWyrm session (auth-only edit form must render, not BookWyrm's login form)",
  ).toBeVisible({ timeout: 30_000 });
});
