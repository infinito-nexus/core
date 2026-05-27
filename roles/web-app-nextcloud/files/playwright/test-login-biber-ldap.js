const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("biber: nextcloud ldap login and logout (native form, ldap backing)", async ({ browser }) => {
    // biber is not autoprovisioned by Nextcloud's local DB — in the
    // pure-native variant (no OIDC, no LDAP) the account simply does
    // not exist, so the test only makes sense when LDAP federation
    // backs the native credential form. The OIDC variant is covered
    // by `biber: nextcloud oidc login and logout`.
    test.skip(
      shared.env.nextcloudOidcEnabled || !shared.env.nextcloudLdapEnabled,
      "biber native login is only meaningful in the native+LDAP variant (services.oidc.enabled=false AND services.ldap.enabled=true); other flavors are covered by the OIDC test.",
    );

    const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const biberPage = await biberContext.newPage();

    try {
      // `loginToStandaloneNextcloudWithRetry` retries once after a
      // 5 s pause — the LDAP-first-login caveat (see
      // roles/web-app-nextcloud/docs/LDAP.md) means biber's NC account
      // is materialised lazily on first successful login, so the very
      // first attempt for a non-admin persona can stall.
      await shared.loginToStandaloneNextcloudWithRetry(
        biberPage,
        shared.env.biberUsername,
        shared.env.biberPassword,
      );

      const shellState = await shared.waitForVisibleCandidate(
        biberPage,
        shared.getNextcloudShellCandidates(biberPage),
        60_000,
        "Timed out waiting for a signed-in Nextcloud shell for biber (native+LDAP)",
      );
      await expect(shellState.locator).toBeVisible();

      await shared.logoutStandaloneNextcloud(biberPage);

      const loginUrl = new URL("login", shared.env.nextcloudBaseUrl).toString();
      await biberPage.goto(loginUrl, { waitUntil: "domcontentloaded", timeout: 60_000 }).catch(() => {});
      const shellAfterLogout = await shared.findFirstVisibleCandidate(shared.getNextcloudShellCandidates(biberPage));
      expect(
        shellAfterLogout,
        "Expected biber to be logged out after clicking Log out (no authenticated Nextcloud shell on /login)"
      ).toBeNull();
    } finally {
      await biberPage.close().catch(() => {});
      await biberContext.close().catch(() => {});
    }
  });
};
