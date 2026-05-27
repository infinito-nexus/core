const { test } = require("@playwright/test");

exports.register = function (shared) {
  test("taiga native login and logout (no oidc / no oauth2)", async ({ page }) => {
    test.skip(
      shared.env.taigaOauth2Enabled || shared.env.taigaOidcEnabled,
      "Native login is only exercised in the variant where neither OIDC nor oauth2 is active — when SSO is on, the OIDC/oauth2 path owns the journey.",
    );

    const session = await shared.loginToTaigaNative(page);
    await shared.logoutFromTaigaNative(page, session);
  });
};
