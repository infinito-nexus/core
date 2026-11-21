const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test("biber: nextcloud oidc login and logout", async ({ browser }) => {
    skipUnlessServiceEnabled("sso");

    const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const biberPage = await biberContext.newPage();

    try {
      await shared.loginToStandaloneNextcloud(biberPage, shared.env.biberUsername, shared.env.biberPassword);

      const shellState = await shared.waitForVisibleCandidate(
        biberPage,
        shared.getNextcloudShellCandidates(biberPage),
        resolveTimeout(60_000),
        "Timed out waiting for a signed-in Nextcloud shell for biber"
      );
      await expect(shellState.locator).toBeVisible();

      await shared.logoutStandaloneNextcloud(biberPage);

      const loginUrl = new URL("login", shared.env.nextcloudBaseUrl).toString();
      await biberPage.goto(loginUrl, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }).catch(() => {});
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
