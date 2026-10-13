const { test } = require("./fixtures/onion-test");

const { runAdminFlow } = require("./personas");

exports.register = function () {
  test("administrator: app → universal logout", async ({ page }) => {
    await runAdminFlow(page);
  });
};
