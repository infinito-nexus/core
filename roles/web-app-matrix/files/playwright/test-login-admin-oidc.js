const { test } = require("./onion-test");

exports.register = function (shared) {
  test("administrator: matrix element OIDC login and logout", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    const { adminUsername, adminPassword } = shared.env;
    const diagnostics = shared.attachDiagnostics(page);
    await shared.signInViaElementOidc(page, adminUsername, adminPassword, "administrator");
    await shared.expectNoCspViolations(page, diagnostics, "matrix element administrator OIDC");
  });
};
