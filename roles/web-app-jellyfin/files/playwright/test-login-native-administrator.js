const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("administrator: native local login (break-glass) lands on the Jellyfin home", async ({ page }) => {
    test.setTimeout(60_000);
    expect(shared.env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminNativePassword, "ADMIN_NATIVE_PASSWORD must be set").toBeTruthy();

    await shared.signInViaLocal(page, shared.env.adminUsername, shared.env.adminNativePassword, "administrator-native");

    await expect(page.locator("body")).toContainText(/home|library|media|jellyfin|dashboard/i, { timeout: 60_000 });

    await shared.logout(page, "administrator-native");
  });
};
