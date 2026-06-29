const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  // Break-glass local login. Semaphore forces LDAP-only form auth when LDAP is
  // enabled, so this local path is only reachable when ldap is disabled (V2).
  test("administrator: native local login (break-glass) lands on authenticated surface", async ({ page }) => {
    test.skip(
      shared.env.ldapEnabled,
      "LDAP_SERVICE_ENABLED=true forces LDAP-only form auth; the local break-glass login is only reachable when ldap is disabled",
    );
    test.setTimeout(60_000);
    expect(shared.env.breakglassUsername, "BREAKGLASS_USERNAME must be set").toBeTruthy();
    expect(shared.env.breakglassPassword, "BREAKGLASS_PASSWORD must be set").toBeTruthy();

    await shared.signInViaLocal(page, shared.env.breakglassUsername, shared.env.breakglassPassword, "administrator-native");

    await expect(page.locator("body")).toContainText(/dashboard|project|task|new project/i, { timeout: 60_000 });

    await shared.logout(page, "administrator-native");
  });
};
