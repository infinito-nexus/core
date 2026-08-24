const { resolveTimeout } = require("./timeouts");
// OIDC login via Keycloak — non-admin RBAC user `biber`. Gated on the `sso`
// service. First-time biber sign-in is JIT-provisioned by Penpot, which needs
// `enable-registration` (default on when OIDC is enabled).
exports.register = (shared) => {
  const { test, expect, skipUnlessServiceEnabled, env, penpotOidcLogin } = shared;

  test("OIDC: biber non-admin RBAC user signs in via Keycloak", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(120_000)); // OIDC round-trip + Keycloak login form
    expect(env.biberUsername).toBeTruthy();
    expect(env.biberPassword).toBeTruthy();
    expect(env.oidcIssuerUrl).toBeTruthy();
    await penpotOidcLogin(page, env.biberUsername, env.biberPassword);
  });
};
