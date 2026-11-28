const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("administrator: Semaphore LDAP login admits the administrator group member as a Semaphore admin", async ({ page }) => {
    shared.skipUnlessLdapLogin();
    test.setTimeout(resolveTimeout(90_000));
    expect(shared.env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

    await shared.signInViaLdap(page, shared.env.adminUsername, shared.env.adminPassword, "administrator-ldap");

    const account = await shared.currentUser(page);
    expect(
      account.admin,
      `the administrator group member MUST carry the Semaphore admin flag after the deploy-time reconcile (account: ${JSON.stringify(account)})`,
    ).toBe(true);
    await gotoOnion(page, `${shared.env.semaphoreBaseUrl}/users`, { waitUntil: "domcontentloaded" });
    await expect(page, "administrator must not be bounced to login on /users").not.toHaveURL(/\/auth\/login/);
    await expect(page.locator("body")).toContainText(/users|new user|admin/i, { timeout: resolveTimeout(60_000) });

    await shared.logout(page, "administrator-ldap");
  });
};
