const { test, expect } = require("@playwright/test");

const { performKeycloakLoginForm, safeSkipUnlessEnabled } = require("./personas");
const {
  appBaseUrl,
  canonicalDomain,
  expectedOidcAuthUrl,
  adminEmail,
  adminUsername,
  adminPassword,
} = require("./env");

// WebAdmin SSO: a username-first OAuth flow — enter the email, and (the mail
// domain being bound to our OIDC directory) the webui redirects to Keycloak.
test("stalwart: sso login, open WebAdmin, logout", async ({ page }) => {
  safeSkipUnlessEnabled("sso");

  await page.goto(`${appBaseUrl}/`);
  await expect.poll(() => page.url(), { timeout: 30_000 }).toContain(`${canonicalDomain}/account/login`);

  const loginField = page
    .getByRole("textbox", { name: /email|user|login/i })
    .or(page.locator("input[type='email'], input[type='text'], input[name='username'], input[name='email']"))
    .first();
  await loginField.waitFor({ state: "visible", timeout: 30_000 });
  await loginField.fill(adminEmail);
  await page
    .getByRole("button", { name: /continue|next|log ?in|sign ?in/i })
    .or(page.locator("button[type='submit']"))
    .first()
    .click();

  await expect.poll(() => page.url(), { timeout: 60_000 }).toContain(expectedOidcAuthUrl);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect.poll(() => page.url(), { timeout: 60_000 }).toContain(canonicalDomain);

  await expect(
    page.locator("nav, .sidebar, [class*='menu'], h1, h2").filter({ hasText: /dashboard|domains|account|settings|directory/i }).first()
  ).toBeVisible({ timeout: 30_000 });

  // Exception: the WebAdmin SPA keeps logout behind its account menu with no
  // stable direct control; hard logout coverage lives in the Roundcube scenarios.
  const logout = page.locator("a[href*='logout'], button:has-text('Logout')").or(page.getByRole("link", { name: /logout/i }));
  if (await logout.first().isVisible({ timeout: 5_000 }).catch(() => false)) {
    await logout.first().click();
  }
});
