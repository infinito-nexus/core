const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { expectNoCspViolations } = require("./personas");
const { skipUnlessServiceDisabled } = require("./service-gating");

exports.register = function (shared) {
  test("administrator: openwebui native signup + sign-in", async ({ page }) => {
    skipUnlessServiceDisabled("sso");
    skipUnlessServiceDisabled("ldap");

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
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    await shared.expectSignInRequiredAfterLogout(page);

    await expectNoCspViolations(page, diagnostics, "openwebui administrator native");
  });
};
