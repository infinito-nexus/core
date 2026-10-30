const { resolveTimeout } = require("./timeouts");
// LDAP-bind login against OpenLDAP — non-admin RBAC user `biber`. Gated on the
// `ldap` service.
exports.register = (shared) => {
  const { test, expect, skipUnlessServiceEnabled, env, penpotLdapLogin, penpotProfile } = shared;

  test("biber: non-admin RBAC user LDAP bind against OpenLDAP", async ({ page }) => {
    skipUnlessServiceEnabled("ldap");
    test.setTimeout(resolveTimeout(90_000)); // LDAP bind + first authenticated render
    expect(env.biberEmail).toBeTruthy();
    expect(env.biberPassword).toBeTruthy();
    await penpotLdapLogin(page, env.biberEmail, env.biberPassword);
    const profile = await penpotProfile(page);
    expect(profile.email, "the user query must resolve biber's directory entry by its e-mail attribute").toBe(env.biberEmail.toLowerCase());
  });
};
