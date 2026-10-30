const { test, expect } = require("@playwright/test");
const { gotoOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("login methods: with SSO on the sign-in page offers the OIDC entry and no disabled entry", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    await gotoOnion(page, `${shared.env.zammadBaseUrl}/#login`, { waitUntil: "domcontentloaded" });

    await expect(page.locator(".login.fullscreen .auth-providers button.auth-provider").first(), "expected the OIDC entry").toBeVisible({
      timeout: resolveTimeout(60_000),
    });
    const form = page.locator(".login.fullscreen form#login");
    if (shared.env.passwordFormShown) {
      await expect(form, "expected the shared form the native or ldap method keeps").toBeVisible();
    } else {
      await expect(form, "user_show_password_login must drop the password form while native and ldap are off").toHaveCount(0);
      await expect(
        page.locator(".login.fullscreen a[href='#admin_password_auth']"),
        "Zammad keeps its admin password-login request as the break-glass entry",
      ).toBeVisible();
    }
    if (!shared.env.loginMethods.registration) {
      await expect(page.locator(".login.fullscreen a[href='#signup']")).toHaveCount(0);
    }
  });

  test("login methods: the API bot administrator signs in through the break-glass password API with SSO on", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    const signin = await shared.signInWithZammadPassword(page, shared.env.adminApiUsername, shared.env.adminApiPassword);
    expect(signin.ok(), `POST /api/v1/signin must keep accepting the local administrator, got ${signin.status()}`).toBe(true);
    await shared.zammadLogout(page);
  });
};
