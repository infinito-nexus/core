const { resolveTimeout } = require("./timeouts");
// Native (local-DB) email/password login for the administrator. Disabled under
// OIDC (disable-login-with-password), so skip when `sso` is on.
exports.register = (shared) => {
  const { test, expect, skipUnlessServiceDisabled, env, penpotNativeLogin } = shared;

  test("administrator: local password login", async ({ page }) => {
    skipUnlessServiceDisabled("sso");
    skipUnlessServiceDisabled("ldap");
    test.setTimeout(resolveTimeout(90_000));
    expect(env.adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
    expect(env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
    await penpotNativeLogin(page, env.adminEmail, env.adminPassword);
  });
};
