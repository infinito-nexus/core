// LDAP-bind login against OpenLDAP — exercised for both the administrator and
// the non-admin RBAC user `biber`. Gated on the `ldap` service.
exports.register = (shared) => {
  const { test, expect, skipUnlessServiceEnabled, env, penpotLdapLogin } = shared;

  test("LDAP: administrator binds against OpenLDAP", async ({ page }) => {
    skipUnlessServiceEnabled("ldap");
    test.setTimeout(90_000); // LDAP bind + first authenticated render
    expect(env.adminEmail).toBeTruthy();
    expect(env.adminPassword).toBeTruthy();
    await penpotLdapLogin(page, env.adminEmail, env.adminPassword);
  });

  test("LDAP: biber non-admin RBAC user binds against OpenLDAP", async ({ page }) => {
    skipUnlessServiceEnabled("ldap");
    test.setTimeout(90_000);
    expect(env.biberEmail).toBeTruthy();
    expect(env.biberPassword).toBeTruthy();
    await penpotLdapLogin(page, env.biberEmail, env.biberPassword);
  });
};
