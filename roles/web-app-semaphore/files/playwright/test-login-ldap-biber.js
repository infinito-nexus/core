const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("biber: Semaphore LDAP login lands on authenticated surface", async ({ page }) => {
    shared.skipUnlessServiceEnabled("ldap");
    test.setTimeout(60_000);
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

    // Semaphore's login form binds against LDAP when SEMAPHORE_LDAP_ACTIVATED is set.
    await shared.signInViaLdap(page, shared.env.biberUsername, shared.env.biberPassword, "biber-ldap");

    await expect(page.locator("body")).toContainText(/dashboard|project|task|new project/i, { timeout: 60_000 });

    await shared.logout(page, "biber-ldap");
  });
};
