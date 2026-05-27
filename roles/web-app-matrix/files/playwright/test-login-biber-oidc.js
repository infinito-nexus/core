const { test } = require("@playwright/test");

exports.register = function (shared) {
  test("biber: matrix element OIDC login and logout", async ({ page }) => {
    shared.skipUnlessServiceEnabled("oidc");
    const { biberUsername, biberPassword } = shared.env;
    const diagnostics = shared.attachDiagnostics(page);
    await shared.signInViaElementOidc(page, biberUsername, biberPassword, "biber");
    await shared.expectNoCspViolations(page, diagnostics, "matrix element biber OIDC");
  });
};
