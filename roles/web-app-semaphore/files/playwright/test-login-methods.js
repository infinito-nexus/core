const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("guest: with SSO on the sign-in page offers the SSO entry and no disabled method", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    await shared.gotoLogin(page);

    await expect(
      shared.oidcButton(page),
      "the Keycloak entry must render on the Semaphore sign-in page",
    ).toBeVisible({ timeout: resolveTimeout(30_000) });
    for (const selector of ["#auth-username", "#auth-password", "[data-testid='auth-signin']"]) {
      const field = page.locator(selector);
      if (shared.env.passwordFormShown) {
        await expect(field.first(), `${selector} must render while the native or the LDAP method is on`).toBeVisible();
      } else {
        await expect(field, `${selector} must not render while only SSO signs in`).toHaveCount(0);
      }
    }
  });
};
