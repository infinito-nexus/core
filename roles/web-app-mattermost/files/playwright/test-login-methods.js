const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test("login methods: with SSO on the sign-in page offers the SSO entry and only the enabled methods", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    const { native, registration } = shared.loginMethods;
    await shared.openMattermostSignIn(page, shared.expectedMattermostBaseUrl());
    await expect(page.locator(shared.SSO_ENTRY).first(), "the sign-in page must offer the Keycloak entry").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
    await expect(page.locator("#input_loginId"), "the login-id field follows the native login method").toHaveCount(
      native ? 1 : 0,
    );
    await expect(page.locator("#input_password-input"), "the password field follows the native login method").toHaveCount(
      native ? 1 : 0,
    );
    await expect(
      page.locator(".login-body-alternate-link"),
      "the account-creation link follows the registration login method",
    ).toHaveCount(registration ? 1 : 0);
  });
};
