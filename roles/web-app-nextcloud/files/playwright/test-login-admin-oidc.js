const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("admin: nextcloud oidc login and logout", async ({ page }) => {
    test.skip(
      !shared.env.nextcloudOidcEnabled,
      "Admin OIDC login is only exercised when services.sso.enabled is true — the native form covers the OIDC-off variant.",
    );

    await shared.loginToStandaloneNextcloud(page);

    const shellState = await shared.waitForVisibleCandidate(
      page,
      shared.getNextcloudShellCandidates(page),
      resolveTimeout(60_000),
      "Timed out waiting for a signed-in Nextcloud shell after the Keycloak login redirect",
    );
    await expect(shellState.locator).toBeVisible();

    // First login can show one or more stacked onboarding dialogs that block clicks.
    await shared.dismissBlockingNextcloudModals(page, page);

    await shared.logoutStandaloneNextcloud(page);
  });
};
