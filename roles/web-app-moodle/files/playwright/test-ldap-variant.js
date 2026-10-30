const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test.describe("moodle LDAP-only (variant 1)", () => {
    test("biber: direct LDAP-bind login via Moodle form", async ({ page }) => {
      skipUnlessServiceEnabled("ldap");
      skipUnlessServiceDisabled("sso");
      await gotoOnion(page, `${shared.env.moodleBaseUrl}/login/index.php`);
      const usernameInput = page.locator("input[name='username'], input#username").first();
      await expect(usernameInput).toBeVisible({ timeout: resolveTimeout(30_000) });
      await usernameInput.fill(shared.env.biberUsername);
      const passwordInput = page.locator(".toggle-sensitive-wrapper input[name='password'], .toggle-sensitive-wrapper input#password").first();
      await expect(passwordInput).toBeAttached({ timeout: resolveTimeout(30_000) });
      await expect(async () => {
        await passwordInput.fill(shared.env.biberPassword);
        await expect(passwordInput).toHaveValue(shared.env.biberPassword);
      }).toPass({ timeout: resolveTimeout(30_000) });
      await page.locator("button[type='submit'], input[type='submit'], #loginbtn").first().click({ timeout: resolveTimeout(30_000) });
      await page.waitForLoadState("load");
      const userMenu = page.locator(".usermenu, [data-region='user-menu-toggle'], a[href*='profile.php']").first();
      await expect(userMenu).toBeVisible({ timeout: resolveTimeout(30_000) });
    });

    test("guest: login page does NOT expose an OIDC entry point", async ({ page }) => {
      skipUnlessServiceEnabled("ldap");
      skipUnlessServiceDisabled("sso");
      await gotoOnion(page, `${shared.env.moodleBaseUrl}/login/index.php`);
      const oidcButton = page.locator("a, button").filter({
        hasText: /openid|oidc|keycloak|single.?sign.?on|sso/i,
      }).first();
      await expect(oidcButton, "OIDC button must NOT be visible in variant 1").toHaveCount(0);
    });
  });
};
