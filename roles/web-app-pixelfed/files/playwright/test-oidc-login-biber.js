const { test } = require("@playwright/test");

exports.register = function (shared) {
  const scenario = shared.loginScenarios.find((s) => s.label === "biber");

  test(`pixelfed oidc login (${scenario.label})`, async ({ page }) => {
    test.skip(!shared.env.oidcEnabled, "OIDC shared service disabled");
    await shared.loginToPixelfed(page, scenario);
    await shared.logoutFromPixelfed(page, scenario);
  });
};
