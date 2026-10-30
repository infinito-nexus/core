const { resolveTimeout } = require("./timeouts");
// LDAP-bind login against OpenLDAP — administrator persona. Gated on `ldap`
// on and `sso` off: under SSO, LDAP accounts sign in through Keycloak.
exports.register = (shared) => {
  const { test, expect, skipUnlessServiceDisabled, skipUnlessServiceEnabled, env, penpotLdapLogin } = shared;

  test("administrator: LDAP bind against OpenLDAP", async ({ page }) => {
    skipUnlessServiceEnabled("ldap");
    skipUnlessServiceDisabled("sso");
    test.setTimeout(resolveTimeout(90_000)); // LDAP bind + first authenticated render
    expect(env.adminEmail).toBeTruthy();
    expect(env.adminPassword).toBeTruthy();
    await penpotLdapLogin(page, env.adminEmail, env.adminPassword);
  });
};
