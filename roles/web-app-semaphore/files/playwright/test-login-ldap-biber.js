const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { withLdapGroupMember } = require("./personas");

exports.register = function (shared) {
  test("biber: Semaphore LDAP login refuses biber without a Semaphore role group", async ({ page }) => {
    shared.skipUnlessLdapLogin();
    test.setTimeout(resolveTimeout(60_000));
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

    const status = await shared.submitLdapLogin(page, shared.env.biberUsername, shared.env.biberPassword);
    expect(
      status,
      "the LDAP search filter MUST only find members of the administrator or user group, so biber without either is refused",
    ).toBe(401);
    await expect
      .poll(() => page.url(), { timeout: resolveTimeout(30_000) })
      .toContain(shared.LOGIN_PATH);
  });

  test("biber: membership in the user group admits biber through the Semaphore LDAP login", async ({ browser }) => {
    shared.skipUnlessLdapLogin();
    test.setTimeout(resolveTimeout(120_000)); // directory group write plus the LDAP login
    await withLdapGroupMember(shared.env.userGroupDn, shared.env.biberDn, async () => {
      const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const page = await ctx.newPage();
        await page.setViewportSize({ width: 1440, height: 1100 });
        await shared.signInViaLdap(page, shared.env.biberUsername, shared.env.biberPassword, "biber-ldap");

        await expect(page.locator("body")).toContainText(/dashboard|project|task|new project/i, { timeout: resolveTimeout(60_000) });
        const account = await shared.currentUser(page);
        expect(account.admin, `a user-group member MUST NOT be a Semaphore admin (account: ${JSON.stringify(account)})`).toBe(false);

        await shared.logout(page, "biber-ldap");
      } finally {
        await ctx.close().catch(() => {});
      }
    });
  });
};
