const { test } = require("@playwright/test");
const { skipUnlessServiceDisabled } = require("./service-gating");

exports.register = function (shared) {
  test("taiga native login and logout (no oidc / no oauth2)", async ({ page }) => {
    skipUnlessServiceDisabled("sso");

    const session = await shared.loginToTaigaNative(page);
    await shared.logoutFromTaigaNative(page, session);
  });
};
