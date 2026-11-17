const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test("login methods: with SSO on the sign-in page offers the SSO entry and only the enabled methods", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    const { registration } = shared.loginMethods;
    await shared.openMattermostSignIn(page, shared.expectedMattermostBaseUrl());
    await expect(
      page.locator(".login-body-card-form"),
      "the native form wrapper the injected script hooks into must render",
    ).toHaveCount(1, { timeout: resolveTimeout(30_000) });
    if (shared.oidcEnabled) {
      await expect(page.locator(shared.SSO_ENTRY).first(), "the sign-in page must offer the Keycloak entry").toBeVisible({
        timeout: resolveTimeout(30_000),
      });
      for (const part of shared.NATIVE_FORM_PARTS) {
        await expect(page.locator(part), `${part} must still render, or the hide rule matches nothing`).not.toHaveCount(0);
        await expect(page.locator(`${part}:visible`), `with SSO on the injected script hides ${part}`).toHaveCount(0);
      }
    } else {
      await expect(page.locator(shared.SSO_ENTRY), "without the sso login method no Keycloak entry is injected").toHaveCount(0);
      await expect(page.locator("#input_loginId"), "without the sso login method the native form stays visible").toBeVisible();
    }
    await expect(
      page.locator(".login-body-alternate-link"),
      "the account-creation link follows the registration login method",
    ).toHaveCount(registration ? 1 : 0);
  });
};
