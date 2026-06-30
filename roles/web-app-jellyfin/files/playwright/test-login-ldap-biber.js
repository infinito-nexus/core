const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("biber: Jellyfin LDAP login (LDAP plugin) lands on the home", async ({ page }) => {
    shared.skipUnlessServiceEnabled("ldap");
    test.setTimeout(60_000);
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

    // The LDAP plugin authenticates via Jellyfin's manual login form.
    await shared.signInViaLdap(page, shared.env.biberUsername, shared.env.biberPassword, "biber-ldap");

    await expect(page.locator("body")).toContainText(/home|library|media|jellyfin/i, { timeout: 60_000 });

    await shared.logout(page, "biber-ldap");
  });
};
