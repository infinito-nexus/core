const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  // Break-glass path: not gated on any service flag (must work in every variant).
  test("administrator: native local login (break-glass) lands on Frappe desk", async ({ page }) => {
    expect(shared.env.adminNativePassword, "ADMIN_NATIVE_PASSWORD must be set").toBeTruthy();

    await shared.signInViaErpnextLocal(page, "Administrator", shared.env.adminNativePassword, "administrator-native");

    await expect(page.locator("body")).toContainText(/desk|workspace|erpnext|home|dashboard/i, { timeout: resolveTimeout(60_000) });

    await shared.erpnextLogout(page);
  });
};
