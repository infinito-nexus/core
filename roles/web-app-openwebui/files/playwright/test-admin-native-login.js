const { test, expect } = require("@playwright/test");

const { expectNoCspViolations } = require("./personas");
const { isServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test("administrator: openwebui native signup + sign-in", async ({ page }) => {
    test.skip(
      isServiceEnabled("oidc"),
      "Native login is only exercised when services.oidc.enabled is false — OIDC mode owns the admin journey and the local password is never set."
    );
    test.skip(
      isServiceEnabled("ldap"),
      "Native login is only exercised when services.ldap.enabled is false — LDAP mode owns the admin journey."
    );

    const diagnostics = shared.attachDiagnostics(page);

    await shared.ensureNativeAdminExists(
      page,
      shared.env.adminUsername,
      shared.env.adminEmail,
      shared.env.adminPassword,
      "administrator"
    );

    await shared.signInViaNativePassword(
      page,
      shared.env.adminEmail,
      shared.env.adminPassword,
      "administrator"
    );

    await expect(
      page.getByRole("img", { name: /open\s+user\s+profile\s+menu/i }).first(),
      "administrator: post-login User profile menu must be visible (proves authenticated chrome rendered, not just the auth page)"
    ).toBeVisible({ timeout: 60_000 });

    await shared.expectSignInRequiredAfterLogout(page);

    await expectNoCspViolations(page, diagnostics, "openwebui administrator native");
  });
};
