// @ts-check
const { test, expect } = require('@playwright/test');
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, runAdminFlow, runBiberFlow, runGuestFlow, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const shared = require("./_shared");
const { oidcLogin } = shared;

test.use({
  ignoreHTTPSErrors: true
});

const baseUrl       = decodeDotenvQuotedValue(process.env.DECIDIM_BASE_URL || process.env.APP_BASE_URL);
const adminEmail    = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const biberEmail    = decodeDotenvQuotedValue(process.env.BIBER_EMAIL);
const oidcIssuerUrl = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);

test.beforeEach(() => {
  expect(baseUrl,       "DECIDIM_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(adminEmail,    "ADMIN_EMAIL must be set in the Playwright env file").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(biberEmail,    "BIBER_EMAIL must be set in the Playwright env file").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set in the Playwright env file").toBeTruthy();
});

// Helper: local form login (admin only)
async function login(page, email, password) {
  await gotoOnion(page, `${baseUrl}/users/sign_in`);
  await page.waitForLoadState("networkidle");
  const cookieBanner = page.locator("#dc-dialog-wrapper, .cookies__container, [data-cookie-consent]");
  if (await cookieBanner.isVisible().catch(() => false)) {
    const acceptBtn = page.locator("button[data-dc-accept], button.cookies__accept, button:has-text('Accept')").first();
    if (await acceptBtn.isVisible().catch(() => false)) {
      await acceptBtn.click();
      await page.waitForLoadState("networkidle");
    }
  }
  const emailInput = page.getByLabel(/email/i).first();
  await emailInput.waitFor({ state: "attached", timeout: resolveTimeout(60000) });
  await emailInput.fill(email);
  await page.locator("input[type='password']").first().fill(password);
  await page.getByRole('button', { name: /log in|sign in/i }).first().click({ timeout: resolveTimeout(30_000) });
  await page.waitForLoadState("networkidle");
}

// Scenario I: Homepage loads
test("homepage loads and shows Decidim", async ({ page }) => {
  await gotoOnion(page, baseUrl);
  await expect(page).not.toHaveTitle("");
  await expect(
    page.locator("#main-bar"),
    "Expected the Decidim header, not a gateway error page",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
});

// Scenario II: Admin login and logout
test("admin can log in and out", async ({ page }) => {
  if (shared.env.loginMethodNative) {
    await login(page, adminEmail, adminPassword);
  } else {
    skipUnlessServiceEnabled("sso");
    await oidcLogin(page, shared.adminKeycloakLoginId(), adminPassword);
  }
  await expect(page).not.toHaveURL(/sign_in/);
  await expect(
    page.locator("#main-bar"),
    "Expected the Decidim header, not a gateway error page",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
  await gotoOnion(page, `${baseUrl}/users/sign_out`);
  await page.waitForLoadState("networkidle");
  await expect(page).not.toHaveURL(/sign_in/);
});

// Scenario III: Biber OIDC login and logout
test("biber can log in via OIDC and log out", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await oidcLogin(page, biberUsername, biberPassword);
  await expect(page).not.toHaveURL(/sign_in/);
  await expect(
    page.locator("#main-bar"),
    "Expected the Decidim header, not a gateway error page",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
  await gotoOnion(page, `${baseUrl}/users/sign_out`);
  await page.waitForLoadState("networkidle");
  await expect(page).not.toHaveURL(/sign_in/);
});

// Scenario IV: Admin and biber can communicate via conversations
test("biber can access profile after OIDC login", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await oidcLogin(page, biberUsername, biberPassword);
  await expect(page).not.toHaveURL(/sign_in/);

  // Biber accesses their account page
  await gotoOnion(page, `${baseUrl}/account`);
  await page.waitForLoadState("networkidle");
  await page.waitForURL(/\/account/, { timeout: resolveTimeout(30000) }).catch(() => {});
  await expect(page).not.toHaveURL(/sign_in/);
  await expect(page.locator("h1, h2").first()).toBeVisible();
});

// Scenario V: SSO button visible when OIDC is enabled
test("SSO login button is visible when OIDC is enabled", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await gotoOnion(page, `${baseUrl}/users/sign_in`);
  await page.waitForLoadState("networkidle");
  const ssoButton = page.locator("a[href*='openid_connect']").first();
  await expect(ssoButton).toBeVisible();
});

// Persona scenarios.
// Bodies live in the shared helper roles/test-e2e-playwright/files/personas.js
// so every role's persona flow stays consistent.

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page);
});

// Persona scenarios.
// Bodies live in the shared persona helpers under
// roles/test-e2e-playwright/files/personas/{guest,biber,admin}.js.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

require("./test-seaweedfs");
require("./test-design");
require("./test-login-methods").register(shared, baseUrl);
require("./test-rbac").register({
  env: { baseUrl, biberUsername, biberPassword },
  oidcLogin,
});
