const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl, gotoOnion } = require("./personas");
const { signInToSite, signOutOfSite } = require("./joomla-session");

const joomlaBaseUrl = normalizeBaseUrl(process.env.JOOMLA_BASE_URL);
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const biberEmail = decodeDotenvQuotedValue(process.env.BIBER_EMAIL);

test.use({ ignoreHTTPSErrors: true });

async function joomlaAdministratorLogout(page) {
  const menu = page.locator(".header-profile .dropdown-toggle").first();
  await menu.click({ timeout: resolveTimeout(30_000) });
  await page
    .locator(".header-profile .dropdown-menu")
    .getByRole("link", { name: /log\s*out/i })
    .first()
    .click({ timeout: resolveTimeout(30_000) });
}

test("administrator: Joomla core LDAP plugin authenticates at /administrator (LDAP variant)", async ({ page }) => {
  expect(joomlaBaseUrl, "JOOMLA_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  await page.context().clearCookies();
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceDisabled("sso");
  const expectedJoomlaBaseUrl = joomlaBaseUrl.replace(/\/$/, "");

  await gotoOnion(page, `${expectedJoomlaBaseUrl}/administrator/index.php?fallback=local`, { waitUntil: "domcontentloaded" });

  const usernameField = page.locator("input[name='username']");
  const passwordField = page.locator("input[name='passwd']");
  await usernameField.waitFor({ state: "visible", timeout: resolveTimeout(60_000) });
  await usernameField.fill(adminUsername);
  await passwordField.fill(adminPassword);
  await Promise.all([
    page.waitForLoadState("domcontentloaded"),
    page.locator("button[type='submit'], input[type='submit']").first().click({ timeout: resolveTimeout(30_000) }),
  ]);

  const controlPanelMarker = page
    .locator("body.com_cpanel, body[class*='option-com_'], #sidebarmenu, nav[aria-label='Main menu'], a[href*='option=com_cpanel']")
    .first();
  const loginErrorAlert = page
    .locator(".alert-warning, .alert-danger, joomla-alert, [role='alert']")
    .filter({ hasText: /Username and password do not match|Login failed|invalid|incorrect/i })
    .first();
  await Promise.race([
    controlPanelMarker.waitFor({ state: "visible", timeout: resolveTimeout(120_000) }),
    loginErrorAlert
      .waitFor({ state: "visible", timeout: resolveTimeout(120_000) })
      .then(async () => {
        const errorText = (await loginErrorAlert.textContent().catch(() => "")) || "(unknown)";
        throw new Error(`Joomla rejected the admin login: ${errorText.trim()}`);
      }),
  ]);

  await joomlaAdministratorLogout(page);

  await expect(page.locator("input[name='username']")).toBeVisible({ timeout: resolveTimeout(15_000) });
});

test("biber: signs in through the core LDAP plugin with the directory uid and mail, then signs out", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceDisabled("sso");
  test.setTimeout(resolveTimeout(120_000));
  expect(joomlaBaseUrl, "JOOMLA_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(biberEmail, "BIBER_EMAIL must be set in the Playwright env file").toBeTruthy();
  await page.context().clearCookies();

  await signInToSite(page, joomlaBaseUrl, biberUsername, biberPassword);
  await gotoOnion(page, `${joomlaBaseUrl}/index.php?option=com_users&view=profile&layout=edit`);
  await expect(
    page.locator("#jform_username"),
    "plg_authentication_ldap must create the account under the directory login attribute",
  ).toHaveValue(biberUsername, { timeout: resolveTimeout(30_000) });
  await expect(
    page.locator("#jform_email1"),
    "plg_authentication_ldap must take the account email from the directory mail attribute",
  ).toHaveValue(biberEmail, { timeout: resolveTimeout(30_000) });
  await expect(
    page.locator("#jform_name"),
    "plg_authentication_ldap must take the account name from the directory full-name attribute",
  ).not.toHaveValue("", { timeout: resolveTimeout(30_000) });

  await signOutOfSite(page, joomlaBaseUrl);
});
