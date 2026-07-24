const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test.describe("moodle LDAP-only (variant 1)", () => {
    test.skip(shared.env.ssoEnabled, "SSO shared service enabled — variant 1 not active");
    test.skip(!shared.env.ldapEnabled, "LDAP shared service disabled");

    test("biber: direct LDAP-bind login via Moodle form", async ({ page }) => {
      await page.goto(`${shared.env.moodleBaseUrl}/login/index.php`);
      const usernameInput = page.locator("input[name='username'], input#username").first();
      await expect(usernameInput).toBeVisible({ timeout: 30_000 });
      await usernameInput.fill(shared.env.biberUsername);
      const passwordInput = page.locator("input[name='password'], input#password").first();
      await expect(async () => {
        await passwordInput.fill(shared.env.biberPassword);
        await expect(passwordInput).toHaveValue(shared.env.biberPassword);
      }).toPass({ timeout: 30_000 });
      await page.locator("button[type='submit'], input[type='submit'], #loginbtn").first().click();
      await page.waitForLoadState("load");
      const userMenu = page.locator(".usermenu, [data-region='user-menu-toggle'], a[href*='profile.php']").first();
      await expect(userMenu).toBeVisible({ timeout: 30_000 });
    });

    test("login page does NOT expose an OIDC entry point", async ({ page }) => {
      await page.goto(`${shared.env.moodleBaseUrl}/login/index.php`);
      const oidcButton = page.locator("a, button").filter({
        hasText: /openid|oidc|keycloak|single.?sign.?on|sso/i,
      }).first();
      await expect(oidcButton, "OIDC button must NOT be visible in variant 1").toHaveCount(0);
    });
  });
};
