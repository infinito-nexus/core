const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceDisabled } = require("./service-gating");

exports.register = function (shared) {
  test("admin: nextcloud native login and logout (no oidc)", async ({ page }) => {
    skipUnlessServiceDisabled("sso");

    // `loginToStandaloneNextcloud` knows the native-flavor password swap
    // (administrator persona uses NEXTCLOUD_DIRECT_LOGIN_PASSWORD when no
    // Keycloak/LDAP federation is in play), so the inline credential
    // typing the OIDC variant does is not safe here.
    await shared.loginToStandaloneNextcloud(page);

    const shellState = await shared.waitForVisibleCandidate(
      page,
      shared.getNextcloudShellCandidates(page),
      resolveTimeout(60_000),
      "Timed out waiting for a signed-in Nextcloud shell after the native login form submit",
    );
    await expect(shellState.locator).toBeVisible();

    // First login can show one or more stacked onboarding dialogs that block clicks.
    await shared.dismissBlockingNextcloudModals(page, page);

    await shared.logoutStandaloneNextcloud(page);
  });
};
