const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion, requireDotenvValue } = require("./personas");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");

const SIGNUP_LINK = "a[href*='/login/signup.php']";

function nativeEnabled() {
  return requireDotenvValue(process.env.LOGIN_METHOD_NATIVE_ENABLED, "LOGIN_METHOD_NATIVE_ENABLED") === "true";
}

function registrationEnabled() {
  return (
    requireDotenvValue(process.env.LOGIN_METHOD_REGISTRATION_ENABLED, "LOGIN_METHOD_REGISTRATION_ENABLED") === "true"
  );
}

exports.register = function (shared) {
  test("login methods: with sso on, Moodle hands the sign-in to Keycloak and offers no self-registration", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("sso");
    test.skip(nativeEnabled(), "the inventory keeps the native form next to the SSO entry");

    await gotoOnion(page, `${shared.env.moodleBaseUrl}/login/index.php`, { waitUntil: "domcontentloaded" });
    await page.waitForURL(/openid-connect\/auth/i, { timeout: resolveTimeout(60_000) });

    await gotoOnion(page, `${shared.env.moodleBaseUrl}/login/index.php?loginredirect=0`, { waitUntil: "domcontentloaded" });
    await expect(
      page.locator("#loginbtn"),
      "loginredirect=0 MUST keep the form reachable as the break-glass page",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
    test.skip(registrationEnabled(), "the inventory switches self-registration on");
    await expect(page.locator(SIGNUP_LINK), "with registration off Moodle MUST NOT offer Create new account").toHaveCount(0);
  });

  test("login methods: without sso, the Moodle form offers no self-registration", async ({ page }) => {
    skipUnlessServiceDisabled("sso");
    test.skip(registrationEnabled(), "the inventory switches self-registration on");

    await gotoOnion(page, `${shared.env.moodleBaseUrl}/login/index.php`, { waitUntil: "domcontentloaded" });
    await expect(page.locator("#loginbtn")).toBeVisible({ timeout: resolveTimeout(60_000) });
    await expect(page.locator(SIGNUP_LINK), "with registration off Moodle MUST NOT offer Create new account").toHaveCount(0);
  });
};
