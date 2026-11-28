const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { apiGetOnion, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test("login methods: with SSO on the sign-in page offers the SSO entry and only the enabled methods", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    const { ldap, native, registration } = shared.loginMethods;
    const base = shared.env.openwebuiBaseUrl;

    const config = await (await apiGetOnion(page.request, `${base}/api/config`)).json();
    expect(config.features?.enable_login_form, "ENABLE_LOGIN_FORM follows the native login method").toBe(native);
    expect(config.features?.enable_ldap, "ENABLE_LDAP follows the ldap login method").toBe(ldap);
    expect(config.features?.enable_signup, "ENABLE_SIGNUP follows the registration login method").toBe(registration);

    await gotoOnion(page, `${base}/auth`);
    await expect(
      page.locator("a, button").filter({ hasText: /continue\s+with|sign\s*in\s+with/i }).first(),
      "the sign-in page must offer the Keycloak entry",
    ).toBeVisible({ timeout: resolveTimeout(30_000) });
    await expect(
      page.locator("#auth-login-card input[type='password']"),
      "the credential form follows the native and ldap login methods",
    ).toHaveCount(native || ldap ? 1 : 0);
    await expect(
      page.locator("#auth-login-card button").filter({ hasText: /^\s*sign\s*up\s*$/i }),
      "the Sign up entry follows the registration login method",
    ).toHaveCount(registration && native ? 1 : 0);
  });
};
