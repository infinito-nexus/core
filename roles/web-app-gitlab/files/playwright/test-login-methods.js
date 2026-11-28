const { test, expect } = require("@playwright/test");

const { gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const loginMethods = {
  native: process.env.LOGIN_METHOD_NATIVE_ENABLED === "true",
  passkey: process.env.LOGIN_METHOD_PASSKEY_ENABLED === "true",
  registration: process.env.LOGIN_METHOD_REGISTRATION_ENABLED === "true",
};

test("login methods: with SSO on the sign-in page offers the SSO entry and only the enabled methods", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await gotoOnion(page, `${base}/users/sign_in`);
  await expect(
    page.locator("form[action*='/users/auth/openid_connect'] button, a[href*='/users/auth/openid_connect']").first(),
    "the sign-in page must offer the Keycloak entry",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
  await expect(
    page.locator("[data-testid='sign-in-form']"),
    "the password form follows the native login method",
  ).toHaveCount(loginMethods.native ? 1 : 0, { timeout: resolveTimeout(30_000) });
  const passkey = page.locator("[data-testid='passkey-form']");
  if (loginMethods.native && loginMethods.passkey) {
    await expect(passkey, "the passkey entry follows the passkey login method").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
  } else {
    await expect(passkey, "the passkey entry follows the passkey login method").toBeHidden({
      timeout: resolveTimeout(30_000),
    });
  }
  await expect(
    page.locator("[data-testid='register-link']"),
    "the Register entry follows the registration login method, and GitLab offers it only next to the password form",
  ).toHaveCount(loginMethods.registration && loginMethods.native ? 1 : 0);
});
