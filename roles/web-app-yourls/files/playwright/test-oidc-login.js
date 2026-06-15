const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.YOURLS_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

test.use({ ignoreHTTPSErrors: true });

// The oauth2-proxy round-trip only proves perimeter auth. The trusted-header
// bridge (user/cache.php shunt_is_valid_user filter) must additionally mint a
// real YOURLS admin session — i.e. YOURLS_USER is defined and the admin chrome
// renders the "Hello <user>" greeting + logout link, NOT YOURLS' own login form.
test("OIDC: oauth2-proxy + trusted-header bridge sign the visitor into a real YOURLS admin session", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "YOURLS_BASE_URL must be set").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  await page.context().clearCookies();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const adminUrl = `${expectedBase}/admin/`;
  const expectedAuth = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await page.goto(adminUrl);
  await expect
    .poll(() => page.url(), { timeout: 60_000, message: `expected redirect to ${expectedAuth}` })
    .toContain(expectedAuth);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect
    .poll(() => page.url(), { timeout: 90_000, message: `expected redirect back to ${adminUrl}` })
    .toContain(adminUrl);

  await page.goto(adminUrl, { waitUntil: "domcontentloaded" });
  await expect(page).toHaveTitle(/yourls/i, { timeout: 30_000 });

  await expect(
    page.locator('input#password[name="password"]'),
    "the trusted-header bridge must sign the visitor in, so YOURLS' own login form must NOT render",
  ).toHaveCount(0);

  await expect(
    page
      .locator('a[href*="action=logout"], a[href*="openid-connect/logout"]')
      .or(page.getByRole("link", { name: /log\s*out/i })),
    "an authenticated YOURLS admin session must expose the logout link",
  ).toBeVisible({ timeout: 30_000 });
  await expect(
    page.locator("body"),
    "the admin chrome must greet the proxied YOURLS_USER",
  ).toContainText(/Hello/i, { timeout: 30_000 });
});
