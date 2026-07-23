const { test } = require("./onion-test");

exports.register = function (shared) {
  test("administrator: matrix element native password login (no oidc)", async ({ page }) => {
    test.skip(
      shared.env.oidcServiceEnabled,
      "Native admin login is only exercised when services.sso.enabled is false — when OIDC is on, the SSO path owns the journey and is covered by 'administrator: matrix element OIDC login and logout'.",
    );
    const { adminUsername, adminPassword } = shared.env;
    const diagnostics = shared.attachDiagnostics(page);
    await shared.signInViaElementPassword(page, adminUsername, adminPassword, "administrator");
    await shared.expectNoCspViolations(page, diagnostics, "matrix element administrator native");
  });
};
