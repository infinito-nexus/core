const { test, expect } = require("@playwright/test");

const { expectNoCspViolations } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test("wordpress administrator can complete an OIDC login round-trip", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("oidc");
    const diagnostics = shared.attachDiagnostics(page);
    await shared.wpAdminLoginViaOidc(
      page,
      shared.env.wpBaseUrl,
      shared.env.adminUsername,
      shared.env.adminPassword
    );
    await expect(page).toHaveURL(/\/wp-admin\/?/, { timeout: 30_000 });
    await shared.wpSignOut(page, shared.env.wpBaseUrl);
    await expectNoCspViolations(
      page,
      diagnostics,
      "wordpress administrator OIDC round-trip"
    );
  });
};
