const { test } = require("./onion-test");

exports.register = function (shared) {
  test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
    await shared.runGuestFlow(page);
  });
};
