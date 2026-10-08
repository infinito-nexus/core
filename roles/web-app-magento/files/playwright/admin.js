const { expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");
const { isServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const ADMIN_MENU = ".menu-wrapper #nav";
const ADMIN = "admin";
const SECOND_FACTOR = "second factor";
const SECOND_FACTOR_PATH = /\/tfa\//;
const TWO_FACTOR_SKIP = "TWO_FACTOR_SERVICE_ENABLED=true: the admin asks for a second factor that no test holds";
const USAGE_NOTICE = ".modal-popup.admin-usage-notification";

/**
 * Returns true when Magento's two-factor modules are switched on, so the password alone does not open the admin.
 */
function twoFactorEnabled() {
  return isServiceEnabled("two_factor");
}

async function landing(page) {
  if (SECOND_FACTOR_PATH.test(new URL(page.url()).pathname)) return SECOND_FACTOR;
  return (await page.locator(ADMIN_MENU).isVisible()) ? ADMIN : "";
}

/**
 * Args:
 *   page: Playwright page of a context without a Magento admin session.
 *
 * Returns "admin" when the password opened the admin, "second factor" when Magento asks for one.
 */
async function adminPasswordSignIn(page) {
  const base = normalizeBaseUrl(process.env.APP_BASE_URL || "");
  const username = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
  const password = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
  const nativePassword = decodeDotenvQuotedValue(process.env.ADMIN_NATIVE_PASSWORD || "");

  expect(base, "APP_BASE_URL must be set").toBeTruthy();
  expect(username, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(nativePassword, "ADMIN_NATIVE_PASSWORD must be set").toBeTruthy();

  await gotoOnion(page, `${base}/admin`);
  if (page.url().includes("openid-connect/auth")) {
    await performKeycloakLoginForm(page, username, password);
    await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).toContain(base);
    await gotoOnion(page, `${base}/admin`);
  }

  await page.locator("#username").fill(username);
  // Playwright prints the value of a fill() that times out, so the field has to be ready before the password goes in.
  await expect(page.locator("#login"), "the password field of the admin sign-in form").toBeEditable({
    timeout: resolveTimeout(60_000),
  });
  await page.locator("#login").fill(nativePassword);
  await page.locator(".action-login").click();
  await expect
    .poll(() => landing(page), {
      message: "the password must lead to an admin page with the menu or to Magento's two-factor page; neither means it was rejected",
      timeout: resolveTimeout(120_000),
    })
    .not.toBe("");
  return landing(page);
}

/**
 * Args:
 *   page: Playwright page of a context without a Magento admin session.
 *
 * Leaves the page on the admin start page, signed in with the password.
 */
async function adminSignIn(page) {
  expect(
    await adminPasswordSignIn(page),
    "the admin asks for a second factor after the password: Magento's two-factor modules are enabled, so a test that enters the admin has to skip on twoFactorEnabled()",
  ).toBe(ADMIN);
}

async function hideUsageNotice(page) {
  await page.addStyleTag({ content: `${USAGE_NOTICE}, ${USAGE_NOTICE} ~ .modals-overlay { display: none !important; }` });
}

module.exports = {
  SECOND_FACTOR,
  TWO_FACTOR_SKIP,
  USAGE_NOTICE,
  adminPasswordSignIn,
  adminSignIn,
  hideUsageNotice,
  twoFactorEnabled,
};
