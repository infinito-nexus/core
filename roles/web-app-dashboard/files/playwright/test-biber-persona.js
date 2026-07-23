const { test } = require("./fixtures/onion-test");

const { runBiberFlow } = require("./personas");

exports.register = function () {
  test("biber: app → universal logout", async ({ page }) => {
    await runBiberFlow(page);
  });
};
