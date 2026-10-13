const { test } = require("@playwright/test");

exports.register = function (shared) {
  test("administrator: app → universal logout", async ({ page }) => {
    await shared.runAdminFlow(page);
  });
};
