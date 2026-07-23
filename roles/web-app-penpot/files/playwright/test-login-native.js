// Native (local-DB) email/password login for the administrator. Disabled under
// OIDC (disable-login-with-password), so skip when `sso` is on.
exports.register = (shared) => {
  const { test, expect, isServiceEnabled, env, penpotNativeLogin } = shared;

  test("native: administrator local password login", async ({ page }) => {
    test.skip(isServiceEnabled("sso"), "native password login is disabled when OIDC is enabled");
    test.skip(isServiceEnabled("ldap"), "native Login button is replaced by the LDAP button when LDAP is enabled");
    test.setTimeout(90_000);
    expect(env.adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();
    expect(env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
    await penpotNativeLogin(page, env.adminEmail, env.adminPassword);
  });
};
