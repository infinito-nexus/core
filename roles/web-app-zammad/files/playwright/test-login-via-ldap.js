const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("biber (ldap): regular sign-in form authenticates against svc-db-openldap", async ({ page }) => {
    shared.skipUnlessServiceEnabled("ldap");
    if (shared.env.oidcEnabled) {
      test.skip(true, "OIDC also enabled — LDAP-form login only exercised in LDAP-only variant (V3)");
    }
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

    await page.context().clearCookies();
    await page.goto(`${shared.env.zammadBaseUrl}/#login`, { waitUntil: "domcontentloaded" });

    const usernameInput = page.locator('input[name="username"]');
    const passwordInput = page.locator('input[name="password"]');
    await usernameInput.waitFor({ state: "visible", timeout: 60_000 });

    await usernameInput.fill(shared.env.biberUsername);
    await passwordInput.fill(shared.env.biberPassword);
    await page.locator('button[type="submit"]').first().click();

    // Body text briefly carries login strings during the redirect; the form-input detachment is the stable signal.
    await expect(usernameInput).toBeHidden({ timeout: 60_000 });
    await expect.poll(() => page.url(), { timeout: 60_000 }).not.toMatch(/#login/);

    await shared.zammadLogout(page);
  });
};
