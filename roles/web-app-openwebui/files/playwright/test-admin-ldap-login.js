const { test, expect } = require("@playwright/test");

const { expectNoCspViolations } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test("administrator: openwebui LDAP login and logout", async ({ page }) => {
    skipUnlessServiceEnabled("ldap");
    const diagnostics = shared.attachDiagnostics(page);

    await shared.signInViaLdap(
      page,
      shared.env.adminUsername,
      shared.env.adminPassword,
      "administrator"
    );

    await expect(
      page.getByRole("img", { name: /open\s+user\s+profile\s+menu/i }).first(),
      "administrator: post-login User profile menu must be visible (proves authenticated chrome rendered, not just the auth page)"
    ).toBeVisible({ timeout: 60_000 });

    await shared.expectSignInRequiredAfterLogout(page);

    await expectNoCspViolations(page, diagnostics, "openwebui administrator LDAP");
  });
};
