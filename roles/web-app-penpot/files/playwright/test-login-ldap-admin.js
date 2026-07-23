const { resolveTimeout } = require("./timeouts");
// LDAP-bind login against OpenLDAP — administrator persona. Gated on the
// `ldap` service.
exports.register = (shared) => {
  const { test, expect, skipUnlessServiceEnabled, env, penpotLdapLogin } = shared;

  test("LDAP: administrator binds against OpenLDAP", async ({ page }) => {
    skipUnlessServiceEnabled("ldap");
    test.setTimeout(resolveTimeout(90_000)); // LDAP bind + first authenticated render
    expect(env.adminEmail).toBeTruthy();
    expect(env.adminPassword).toBeTruthy();
    await penpotLdapLogin(page, env.adminEmail, env.adminPassword);
  });
};
