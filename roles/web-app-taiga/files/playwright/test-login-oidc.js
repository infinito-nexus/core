const { test } = require("@playwright/test");

exports.register = function (shared) {
  test("taiga oidc login and logout", async ({ page }) => {
    test.skip(
      !shared.env.taigaOauth2Enabled && !shared.env.taigaOidcEnabled,
      "OIDC/oauth2 path requires at least one of the two services to be enabled — the native LDAP/local form covers the remaining variant.",
    );

    const session = await shared.loginToTaiga(page);
    await shared.logoutFromTaiga(page, session);
  });
};
