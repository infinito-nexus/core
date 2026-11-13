const { test, expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const MENU_BAR = "[data-test='app-menu-bar']";
const REGISTRATION = /\/mfa\/register/;
const AUTHENTICATOR_SETUP = "button[name='authenticator'][value='SETUP']";

const base = decodeDotenvQuotedValue(process.env.APP_BASE_URL).replace(/\/$/, "");
const internalLogin = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const twoFactorEnforced = process.env.LOGIN_METHOD_2FA_ENFORCED === "true";

function register() {
  test("2fa enrollment: with its own second factor enforced pgAdmin holds the administrator on the MFA registration before the browser", async ({ page }) => {
    test.skip(!internalLogin, "LOGIN_METHOD_NATIVE_ENABLED=false");
    test.skip(!twoFactorEnforced, "LOGIN_METHOD_2FA_ENFORCED=false");

    await gotoOnion(page, `${base}/login`);
    const email = page.locator("input[name='email']");
    await expect(email).toBeEditable({ timeout: resolveTimeout(30_000) });
    await email.fill(decodeDotenvQuotedValue(process.env.ADMIN_EMAIL));
    await page.locator("input[name='password']").fill(decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD));
    await page.locator("button[name='internal_button']").click();

    await expect(page, "the sign-in must end on the MFA registration").toHaveURL(REGISTRATION, {
      timeout: resolveTimeout(60_000),
    });
    await expect(page.getByText("Authentication Registration", { exact: true }).first(), "pgAdmin must render its registration page").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
    await expect(page.locator(AUTHENTICATOR_SETUP), "the registration must offer the authenticator setup").toBeVisible();

    await gotoOnion(page, `${base}/browser/`);
    await expect(page, "the browser must send the account back to the registration").toHaveURL(REGISTRATION, {
      timeout: resolveTimeout(60_000),
    });
    await expect(page.locator(MENU_BAR), "the browser must stay out of reach until a second factor is registered").toHaveCount(0);
  });
}

module.exports = { register };
