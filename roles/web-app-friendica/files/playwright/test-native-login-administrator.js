const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  async function loginAndLogout(page, login) {
    await login(page, shared.env.adminUsername, shared.env.adminPassword);
    await shared.friendicaLogout(page);
    await gotoOnion(page, `${shared.trimmedBaseUrl()}/network`, { waitUntil: "domcontentloaded" }).catch(() => {});
    await expect(page.locator("a[href*='/logout']")).not.toBeAttached({ timeout: resolveTimeout(10_000) });
  }

  test("administrator: friendica native login and logout", async ({ page }) => {
    shared.skipUnlessServiceEnabled("ldap");
    await loginAndLogout(page, shared.loginViaFriendica);
  });
};
