const { test, expect } = require("@playwright/test");

const { gotoOnion } = require("./personas");
const {
  appBaseUrl,
  canonicalDomain,
  oidcIssuerUrl,
  stalwartAdminUsername,
  stalwartAdminPassword,
} = require("./env");
const { resolveTimeout } = require("./timeouts");

// The account is Stalwart's recovery admin (STALWART_ADMIN_USER), not the platform's administrator:
// discovery sends it to Stalwart's own OAuth server even when Keycloak serves the mail domain, so this
// journey runs with and without SSO.
test("administrator: stalwart recovery admin native login and logout", async ({ page }) => {
  expect(stalwartAdminUsername, "STALWART_ADMIN_USERNAME must be set").toBeTruthy();
  expect(stalwartAdminPassword, "STALWART_ADMIN_PASSWORD must be set").toBeTruthy();

  await gotoOnion(page, `${appBaseUrl}/`);
  await expect.poll(() => page.url(), { timeout: resolveTimeout(30_000) }).toContain(`${canonicalDomain}/account/login`);

  const loginField = page
    .getByRole("textbox", { name: /email|user|login/i })
    .or(page.locator("input[type='email'], input[type='text'], input[name='username'], input[name='email']"))
    .first();
  await loginField.waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
  await loginField.fill(stalwartAdminUsername);

  await page
    .getByRole("button", { name: /continue/i })
    .or(page.locator("button[type='submit']"))
    .first()
    .click();

  // Stalwart v1.0.0 asks consent for the OAuth client before the password form; v1.0.1 shows the password form directly.
  const allow = page.getByRole("button", { name: /^allow$/i });
  const passwordField = page.locator("input[type='password'], input[name='password']").first();
  await allow.or(passwordField).first().waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
  if (await allow.isVisible()) {
    await allow.click();
  }

  await passwordField.waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
  await passwordField.fill(stalwartAdminPassword);
  await page
    .getByRole("button", { name: /sign ?in|log ?in/i })
    .or(page.locator("button[type='submit']"))
    .first()
    .click();

  await expect(
    page.getByText(/invalid username or password/i)
  ).toBeHidden({ timeout: resolveTimeout(15_000) });

  const dashboard = page
    .locator("nav, .sidebar, [class*='menu'], h1, h2")
    .filter({ hasText: /dashboard|domains|account|settings|directory/i })
    .first();
  await allow.or(dashboard).first().waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
  if (await allow.isVisible()) {
    await allow.click();
  }
  await expect(dashboard).toBeVisible({ timeout: resolveTimeout(30_000) });

  if (oidcIssuerUrl) {
    expect(page.url()).not.toContain(oidcIssuerUrl);
  }
  await expect.poll(() => page.url(), { timeout: resolveTimeout(15_000) }).toContain(canonicalDomain);

  const logout = page.locator("a[href*='logout'], button:has-text('Logout')").or(page.getByRole("link", { name: /logout/i }));
  if (await logout.first().isVisible().catch(() => false)) {
    await logout.first().click();
    await expect.poll(() => page.url(), { timeout: resolveTimeout(30_000) }).toContain("/account/login");
  }
});
