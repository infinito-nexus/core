const { test, expect } = require("@playwright/test");

const { safeIsEnabled, gotoOnion } = require("./personas");
const {
  appBaseUrl,
  canonicalDomain,
  oidcIssuerUrl,
  stalwartAdminUsername,
  stalwartAdminPassword,
} = require("./env");
const { resolveTimeout } = require("./timeouts");

// WebAdmin native login: the variant where Keycloak is absent and Stalwart's own
// directory owns the credentials. Without this the sso=false variant deploys a
// login surface no spec ever exercises, because every other spec self-skips on sso.
// The account is Stalwart's own WebAdmin administrator (STALWART_ADMIN_USER), not the
// platform's administrator — the latter lives in the OIDC directory and is rejected here.
test("administrator: stalwart native login and logout (no sso)", async ({ page }) => {
  test.skip(
    safeIsEnabled("sso"),
    "Native login is only exercised in the variant without Keycloak — when SSO is on the OIDC path owns the journey.",
  );
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

  // Exception: WebAdmin asks for the account name on its own screen ("Enter your account
  // name to continue"); the password field only exists after Continue, so waiting for it
  // on the first screen never resolves.
  await page
    .getByRole("button", { name: /continue/i })
    .or(page.locator("button[type='submit']"))
    .first()
    .click();

  const passwordField = page.locator("input[type='password'], input[name='password']").first();
  await passwordField.waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
  await passwordField.fill(stalwartAdminPassword);
  await page
    .getByRole("button", { name: /sign ?in|log ?in/i })
    .or(page.locator("button[type='submit']"))
    .first()
    .click();

  // Exception: a rejected credential re-renders the same form rather than erroring, so
  // without this the run would fail later on the dashboard locator with no reason given.
  await expect(
    page.getByText(/invalid username or password/i)
  ).toBeHidden({ timeout: resolveTimeout(15_000) });

  await expect(
    page.locator("nav, .sidebar, [class*='menu'], h1, h2").filter({ hasText: /dashboard|domains|account|settings|directory/i }).first()
  ).toBeVisible({ timeout: resolveTimeout(30_000) });

  // Exception: the whole point of this spec is that the journey stays on Stalwart;
  // a redirect to the issuer would mean the sso=false variant still hit Keycloak.
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
