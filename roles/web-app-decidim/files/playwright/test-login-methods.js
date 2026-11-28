const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const SIGN_IN_FORM = "#session_new_user:visible";
const SIGN_UP_ENTRY = "a[href*='/users/sign_up']:visible";
const PASSWORD_RESET_ENTRY = "a[href*='/users/password/new']:visible";

exports.register = function (shared, baseUrl) {
  test("login methods: with SSO on the sign-in page offers the SSO entry and none of the disabled ones", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    await gotoOnion(page, `${baseUrl}/users/sign_in`);
    await page.waitForLoadState("networkidle");

    if (shared.env.loginMethodSso) {
      await expect(page.locator(shared.SSO_ENTRY).first(), "the OpenID Connect entry must render on the sign-in page").toBeVisible({
        timeout: resolveTimeout(30_000),
      });
    }
    if (!shared.env.loginMethodNative) {
      await expect(page.locator(SIGN_IN_FORM), "the local password form must be gone while native sign-in is off").toHaveCount(0);
      await expect(page.locator(PASSWORD_RESET_ENTRY), "the password reset entry must be gone while native sign-in is off").toHaveCount(0);
    }
    if (!shared.env.loginMethodRegistration) {
      await expect(page.locator(SIGN_UP_ENTRY), "the sign-up entry must be gone while registration is off").toHaveCount(0);
    }
  });
};
