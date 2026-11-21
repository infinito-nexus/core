const { test, expect } = require("@playwright/test");
const { gotoOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const LOGIN_CARD = "section.for-login .page-card";

exports.register = function (shared) {
  test("login methods: with SSO on the sign-in page offers the Keycloak entry and no disabled entry", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    const methods = shared.env.loginMethods;
    await gotoOnion(page, `${shared.env.erpnextBaseUrl}/login`);

    await expect(page.locator(`${LOGIN_CARD} a.btn-login-option.btn-keycloak`), "expected the Social Login Key entry").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
    await expect(page.locator(`${LOGIN_CARD} #login_password`)).toHaveCount(shared.env.localFormShown ? 1 : 0);
    await expect(page.locator(`${LOGIN_CARD} .page-card-actions button[type='submit']`)).toHaveCount(methods.native ? 1 : 0);
    await expect(page.locator(`${LOGIN_CARD} .btn-ldap-login`)).toHaveCount(methods.ldap ? 1 : 0);
    await expect(page.locator(`${LOGIN_CARD} .btn-login-with-email-link`)).toHaveCount(methods.email ? 1 : 0);
    await expect(page.locator(`${LOGIN_CARD} a[href='#signup']`)).toHaveCount(methods.registration && methods.native ? 1 : 0);
  });

  test("login methods: the API bot token stays the break-glass path into the ERPNext API", async () => {
    const api = await shared.breakGlassApi();
    try {
      const logged = await api.get(`${shared.env.erpnextBaseUrl}/api/method/frappe.auth.get_logged_user`, {
        timeout: resolveTimeout(60_000),
      });
      expect(logged.status(), "the API bot token must authenticate whatever disable_user_pass_login says").toBe(200);
      expect((await logged.json()).message, "the token must not fall back to Guest").not.toBe("Guest");
    } finally {
      await api.dispose().catch(() => {});
    }
  });
};
