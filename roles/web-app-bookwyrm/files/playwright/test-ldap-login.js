const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { normalizeBaseUrl, decodeDotenvQuotedValue, performKeycloakLoginForm } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.BOOKWYRM_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

test.use({ ignoreHTTPSErrors: true });

test("LDAP: Keycloak LDAP federation + trusted-header SSO sign the visitor into BookWyrm (variant 1)", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceEnabled("sso");
  expect(adminUsername).toBeTruthy();
  expect(adminPassword).toBeTruthy();
  await page.context().clearCookies();

  const expectedBase = baseUrl.replace(/\/$/, "");
  await page.goto(`${expectedBase}/`);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect.poll(() => page.url(), { timeout: 90_000 }).toContain(expectedBase);
  await expect(page.locator("body")).toBeVisible({ timeout: 60_000 });

  await page.goto(`${expectedBase}/preferences/profile`, { waitUntil: "domcontentloaded" });
  await expect(
    page.locator('form[name="edit-profile"]'),
    "trusted-header SSO must sign the LDAP-federated visitor into a real BookWyrm session (auth-only edit form must render, not BookWyrm's login form)",
  ).toBeVisible({ timeout: 30_000 });
});
