const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

// biber + administrator side-by-side: two isolated browser contexts log in
// independently, biber logs out first, admin session must persist. Exercises
// ldapauth's bridge for a non-admin LDAP user AND verifies session isolation
// between contexts. Skips when LDAP is disabled.

exports.register = function (shared) {
  async function sideBySide(browser, login) {
    const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      const biberPage = await biberContext.newPage();
      await login(biberPage, shared.env.biberUsername, shared.env.biberPassword);

      const adminPage = await adminContext.newPage();
      await login(adminPage, shared.env.adminUsername, shared.env.adminPassword);

      await shared.friendicaLogout(biberPage);
      await adminPage.goto(`${shared.trimmedBaseUrl()}/network`, { waitUntil: "domcontentloaded" });
      await expect(
        adminPage.locator("#topbar-first, #navbar-apps-menu, a[href*='/logout']").first(),
      ).toBeVisible({ timeout: resolveTimeout(10_000) });

      await shared.friendicaLogout(adminPage);
    } finally {
      await biberContext.close().catch(() => {});
      await adminContext.close().catch(() => {});
    }
  }

  test("biber: biber ↔ administrator: side by side in isolated friendica contexts, biber's logout keeps the administrator signed in", async ({ browser }) => {
    shared.skipUnlessServiceEnabled("ldap");
    await sideBySide(browser, shared.loginViaFriendica);
  });
};
