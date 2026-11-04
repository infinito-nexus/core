const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion, isAuthChain, performKeycloakLoginForm } = require("./personas");

const ACTION = { timeout: resolveTimeout(30_000) };
const SITE_USERNAME = "main input[name='username']";
const SITE_PASSWORD = "main input[name='password']";
const SITE_SUBMIT = "main form button[type='submit'].btn-primary";
const SITE_PROFILE = "main .com-users-profile";
const SITE_SESSION = "main .com-users-profile, main .com-users-logout";
const ADMIN_FORM = "#form-login";
const ADMIN_USERNAME = "#mod-login-username";
const ADMIN_PASSWORD = "#mod-login-password";
const ADMIN_SUBMIT = "#btn-login-submit";
const ADMIN_CONTENT = "body.com_cpanel #content";
const ADMIN_SEARCH = "form#adminForm #filter_search";
const ADMIN_ROW = "form#adminForm table tbody tr";
const TOUR = ".shepherd-element";
const TOUR_CLOSE = ".shepherd-cancel-icon";

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Args:
 *   page: Playwright page without a Joomla session; ends on the profile of the signed-in account.
 *   base: Joomla base URL without a trailing slash.
 *   username: Keycloak username.
 *   password: Keycloak password.
 */
async function signInViaKeycloak(page, base, username, password) {
  await gotoOnion(page, `${base}/`);
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "plg_system_keycloak must send a guest to the Keycloak authorization endpoint",
    })
    .toContain("/protocol/openid-connect/auth");
  await performKeycloakLoginForm(page, username, password);
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `the OIDC callback must land back on ${base}`,
    })
    .toContain(base);
  expect(
    page.url(),
    `the OIDC callback for ${username} must not end on the plugin's index.php?fallback=local SSO-error page`,
  ).not.toContain("fallback=local");
  await gotoOnion(page, `${base}/index.php?option=com_users&view=profile`);
  await expect(
    page.locator(SITE_PROFILE).first(),
    `com_users must render the profile of ${username}, which it does only for a signed-in account`,
  ).toBeVisible(ACTION);
}

/**
 * Args:
 *   page: Playwright page without a Joomla session; ends on the profile of the signed-in account.
 *   base: Joomla base URL without a trailing slash.
 *   username: Joomla or directory username.
 *   password: its password.
 */
async function signInToSite(page, base, username, password) {
  await gotoOnion(page, `${base}/index.php?option=com_users&view=login&fallback=local`);
  await expect(page.locator(SITE_USERNAME), "the com_users login form must render").toBeEditable(ACTION);
  await page.locator(SITE_USERNAME).fill(username);
  await expect(page.locator(SITE_PASSWORD)).toBeEditable(ACTION);
  await page.locator(SITE_PASSWORD).fill(password);
  await page.locator(SITE_SUBMIT).first().click(ACTION);
  await expect(
    page.locator(SITE_SESSION).first(),
    `Joomla must accept ${username} at the site login form`,
  ).toBeVisible(ACTION);
}

/**
 * Args:
 *   page: Playwright page with a site session; ends on a page without one.
 *   base: Joomla base URL without a trailing slash.
 */
async function signOutOfSite(page, base) {
  await gotoOnion(page, `${base}/index.php?option=com_users&view=login`);
  const logout = page.locator("main .com-users-logout").getByRole("button", { name: /log\s*out/i });
  await expect(logout, "com_users must offer its Log out button to a signed-in account").toBeVisible(ACTION);
  await logout.click(ACTION);
  await expect
    .poll(
      async () =>
        isAuthChain(page.url()) || (await page.locator(SITE_USERNAME).isVisible().catch(() => false)),
      { timeout: resolveTimeout(60_000), message: "after Log out Joomla must ask for credentials again" },
    )
    .toBe(true);
}

/**
 * Args:
 *   page: Playwright page on the control panel right after the sign-in; returns once no guided tour covers it.
 */
async function dismissTour(page) {
  let autostart = null;
  await expect
    .poll(
      async () => {
        autostart = await page
          .evaluate(() =>
            document.readyState === "complete" && window.Joomla && window.Joomla.getOptions
              ? String(window.Joomla.getOptions("com_guidedtours.autotour") || "")
              : null,
          )
          .catch(() => null);
        return autostart;
      },
      { message: "the control panel must tell whether a guided tour starts", ...ACTION },
    )
    .not.toBeNull();
  if (autostart === "") return;
  await expect(page.locator(TOUR_CLOSE).first()).toBeVisible(ACTION);
  await page.locator(TOUR_CLOSE).first().click(ACTION);
  await expect(page.locator(TOUR).first()).toBeHidden(ACTION);
}

/**
 * Args:
 *   page: Playwright page without an administrator session; ends on the control panel.
 *   base: Joomla base URL without a trailing slash.
 *   username: local Joomla administrator.
 *   password: its password.
 */
async function signInToAdministrator(page, base, username, password) {
  await gotoOnion(page, `${base}/administrator/index.php?fallback=local`);
  await expect(page.locator(`${ADMIN_FORM}, ${ADMIN_CONTENT}`).first()).toBeVisible(ACTION);
  if (await page.locator(ADMIN_FORM).isVisible()) {
    await expect(page.locator(ADMIN_USERNAME)).toBeEditable(ACTION);
    await page.locator(ADMIN_USERNAME).fill(username);
    await expect(page.locator(ADMIN_PASSWORD)).toBeEditable(ACTION);
    await page.locator(ADMIN_PASSWORD).fill(password);
    await page.locator(ADMIN_SUBMIT).click(ACTION);
  }
  await expect(page.locator(ADMIN_CONTENT).first(), "the administrator must reach the control panel").toBeVisible(ACTION);
  await dismissTour(page);
}

/**
 * Args:
 *   page: Playwright page with an administrator session.
 *   base: Joomla base URL without a trailing slash.
 *   username: account whose row of the user manager is returned.
 * Returns:
 *   Locator: the visible row of that account in Users: Manage.
 */
async function userManagerRow(page, base, username) {
  await gotoOnion(page, `${base}/administrator/index.php?option=com_users&view=users`);
  const search = page.locator(ADMIN_SEARCH);
  await expect(search, "Users: Manage must offer its search box").toBeEditable(ACTION);
  await search.fill(username);
  await search.press("Enter");
  const row = page
    .locator(ADMIN_ROW)
    .filter({ hasText: new RegExp(`\\b${escapeRegExp(username)}\\b`) })
    .first();
  await expect(row, `Users: Manage must list ${username}`).toBeVisible(ACTION);
  return row;
}

module.exports = {
  signInViaKeycloak,
  signInToSite,
  signOutOfSite,
  signInToAdministrator,
  userManagerRow,
};
