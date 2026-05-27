const { test, expect } = require("@playwright/test");

// biber + administrator side-by-side: two isolated browser contexts log in
// independently, biber logs out first, admin session must persist. Exercises
// ldapauth's bridge for a non-admin LDAP user AND verifies session isolation
// between contexts. Skips when LDAP is disabled.

exports.register = function (shared) {
  test("friendica: biber + administrator side by side in isolated contexts", async ({ browser }) => {
    shared.skipUnlessServiceEnabled("ldap");

    const login = shared.pickLoginPath();
    const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      const biberPage = await biberContext.newPage();
      await login(biberPage, shared.env.biberUsername, shared.env.biberPassword);

      const adminPage = await adminContext.newPage();
      await login(adminPage, shared.env.adminUsername, shared.env.adminPassword);

      // biber logs out first — admin session must stay alive.
      await shared.friendicaLogout(biberPage);
      await adminPage.goto(`${shared.trimmedBaseUrl()}/network`, { waitUntil: "domcontentloaded" });
      await expect(
        adminPage.locator("#topbar-first, #navbar-apps-menu, a[href*='/logout']").first(),
      ).toBeVisible({ timeout: 10_000 });

      await shared.friendicaLogout(adminPage);
    } finally {
      await biberContext.close().catch(() => {});
      await adminContext.close().catch(() => {});
    }
  });
};
