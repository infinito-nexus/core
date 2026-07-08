const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("biber (ldap): regular sign-in form authenticates against svc-db-openldap", async ({ page }) => {
    shared.skipUnlessServiceEnabled("ldap");
    if (shared.env.oidcEnabled) {
      test.skip(true, "OIDC also enabled — LDAP-form login only exercised in LDAP-only variant (V3)");
    }
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

    await page.context().clearCookies();
    await gotoOnion(page, `${shared.env.zammadBaseUrl}/#login`, { waitUntil: "domcontentloaded" });

    const usernameInput = page.locator('input[name="username"]');
    const passwordInput = page.locator('input[name="password"]');
    await usernameInput.waitFor({ state: "visible", timeout: resolveTimeout(60_000) });

    await usernameInput.fill(shared.env.biberUsername);
    await passwordInput.fill(shared.env.biberPassword);
    await page.locator('button[type="submit"]').first().click();

    // Body text briefly carries login strings during the redirect; the form-input detachment is the stable signal.
    await expect(usernameInput).toBeHidden({ timeout: resolveTimeout(60_000) });
    await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).not.toMatch(/#login/);

    await shared.zammadLogout(page);
  });
};
