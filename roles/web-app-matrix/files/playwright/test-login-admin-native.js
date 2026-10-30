const { test } = require("./onion-test");

exports.register = function (shared) {
  test("administrator: matrix element native password login (no oidc)", async ({ page }) => {
    shared.skipUnlessServiceDisabled("sso");
    const { adminUsername, adminPassword } = shared.env;
    const diagnostics = shared.attachDiagnostics(page);
    await shared.signInViaElementPassword(page, adminUsername, adminPassword, "administrator");
    await shared.expectNoCspViolations(page, diagnostics, "matrix element administrator native");
  });
};
