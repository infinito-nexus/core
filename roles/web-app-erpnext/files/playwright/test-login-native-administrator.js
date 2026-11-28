const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("administrator: native local login lands on Frappe desk while the native method is on", async ({ page }) => {
    test.skip(!shared.env.loginMethods.native, "LOGIN_METHOD_NATIVE_ENABLED=false: disable_user_pass_login refuses the password form");
    expect(shared.env.adminNativePassword, "ADMIN_NATIVE_PASSWORD must be set").toBeTruthy();

    await shared.signInViaErpnextLocal(page, "Administrator", shared.env.adminNativePassword, "administrator-native");

    await expect(page.locator("body")).toContainText(/desk|workspace|erpnext|home|dashboard/i, { timeout: resolveTimeout(60_000) });

    await shared.erpnextLogout(page);
  });

  test("administrator: the password sign-in is refused while the native method is off", async ({ browser }) => {
    test.skip(shared.env.loginMethods.native, "LOGIN_METHOD_NATIVE_ENABLED=true");
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      const login = await context.request.post(`${shared.env.erpnextBaseUrl}/api/method/login`, {
        form: { usr: "Administrator", pwd: shared.env.adminNativePassword },
        timeout: resolveTimeout(60_000),
      });
      expect(login.status(), "disable_user_pass_login must refuse the Administrator password").not.toBe(200);
    } finally {
      await context.close().catch(() => {});
    }
  });
};
