const { test } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  const scenario = shared.loginScenarios.find((s) => s.label === "biber");

  test(`pixelfed oidc login (${scenario.label})`, async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    shared.skipWhenBiberMailboxFailsPixelfedValidation();
    await shared.loginToPixelfed(page, scenario);
    await shared.logoutFromPixelfed(page, scenario);
  });
};
