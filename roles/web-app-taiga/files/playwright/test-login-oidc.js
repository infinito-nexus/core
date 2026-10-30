const { test } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test("taiga oidc login and logout", async ({ page }) => {
    skipUnlessServiceEnabled("sso");

    const session = await shared.loginToTaiga(page);
    await shared.logoutFromTaiga(page, session);
  });
};
