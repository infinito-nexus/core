const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("administrator: native local login (break-glass) lands on authenticated surface", async ({ page }) => {
    // nocheck: playwright-sso-ldap-gate -- gates on the ldap login method, whose LDAP login refuses every local account
    test.skip(shared.env.loginMethodLdap, "Semaphore's LDAP login refuses every local account, the break-glass account included");
    test.setTimeout(resolveTimeout(60_000));
    expect(shared.env.breakglassUsername, "BREAKGLASS_USERNAME must be set").toBeTruthy();
    expect(shared.env.breakglassPassword, "BREAKGLASS_PASSWORD must be set").toBeTruthy();

    if (shared.env.loginMethodNative) {
      await shared.signInViaLocal(page, shared.env.breakglassUsername, shared.env.breakglassPassword, "administrator-native");
    } else {
      await shared.signInViaBreakglassApi(page, shared.env.breakglassUsername, shared.env.breakglassPassword, "administrator-breakglass");
    }

    await expect(page.locator("body")).toContainText(/dashboard|project|task|new project/i, { timeout: resolveTimeout(60_000) });

    await shared.logout(page, "administrator-native");
  });
};
