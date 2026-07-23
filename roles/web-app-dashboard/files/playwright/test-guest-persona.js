const { test } = require("./fixtures/onion-test");

const { runGuestFlow } = require("./personas");

exports.register = function () {
  test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
    await runGuestFlow(page);
  });
};
