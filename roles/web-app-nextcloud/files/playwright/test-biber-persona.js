const { test } = require("@playwright/test");

exports.register = function (shared) {
  test("biber: app → universal logout", async ({ page }) => {
    await shared.runBiberFlow(page);
  });
};
