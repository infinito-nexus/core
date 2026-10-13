const { test, expect } = require("@playwright/test");
const { apiGetOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("administrator: the native account signs in with its password and holds Admin and Agent while sso is off", async ({ page }) => {
    test.skip(shared.env.oidcEnabled, "with sso on the administrator signs in through the identity provider");
    expect(shared.env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

    const signin = await shared.signInWithZammadPassword(page, shared.env.adminUsername, shared.env.adminPassword);
    expect(signin.ok(), `the administrator from the users lookup must sign in with its password, got ${signin.status()}`).toBe(true);

    const me = await apiGetOnion(page.context().request, `${shared.env.zammadBaseUrl}/api/v1/users/me?expand=true`, {
      headers: { Accept: "application/json" },
    });
    expect(me.ok(), `users/me answered ${me.status()}`).toBe(true);
    const account = await me.json();
    expect(account.login, "the session belongs to the administrator").toBe(shared.env.adminUsername);
    expect(account.email, "the administrator keeps the e-mail of the users lookup").toBe(shared.env.adminEmail);
    expect(account.active, "the administrator is active").toBe(true);
    expect(account.roles, "the administrator holds Admin and Agent").toEqual(expect.arrayContaining(["Admin", "Agent"]));
  });

  test("administrator: zammad OIDC login lands on authenticated surface", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    expect(shared.env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
    expect(shared.env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();

    await shared.signInViaZammadOidc(page, shared.env.adminUsername, shared.env.adminPassword, "administrator");

    await expect(page.locator("body")).toContainText(/dashboard|ticket|overview|zammad/i, { timeout: resolveTimeout(60_000) });

    await shared.zammadLogout(page);
  });
};
