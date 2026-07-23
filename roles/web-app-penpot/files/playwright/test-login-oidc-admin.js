const { resolveTimeout } = require("./timeouts");
// OIDC login via Keycloak — administrator persona. Gated on the `sso` service.
exports.register = (shared) => {
  const { test, expect, skipUnlessServiceEnabled, env, penpotOidcLogin } = shared;

  test("OIDC: administrator signs in via Keycloak", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(120_000)); // OIDC round-trip + Keycloak login form
    expect(env.adminUsername).toBeTruthy();
    expect(env.adminPassword).toBeTruthy();
    expect(env.oidcIssuerUrl).toBeTruthy();
    await penpotOidcLogin(page, env.adminUsername, env.adminPassword);
  });
};
