// OIDC login via Keycloak — exercised for both the administrator and the
// non-admin RBAC user `biber`. Gated on the `sso` service.
exports.register = (shared) => {
  const { test, expect, skipUnlessServiceEnabled, env, penpotOidcLogin } = shared;

  test("OIDC: administrator signs in via Keycloak", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(120_000); // OIDC round-trip + Keycloak login form
    expect(env.adminUsername).toBeTruthy();
    expect(env.adminPassword).toBeTruthy();
    expect(env.oidcIssuerUrl).toBeTruthy();
    await penpotOidcLogin(page, env.adminUsername, env.adminPassword);
  });

  test("OIDC: biber non-admin RBAC user signs in via Keycloak", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(120_000);
    expect(env.biberUsername).toBeTruthy();
    expect(env.biberPassword).toBeTruthy();
    expect(env.oidcIssuerUrl).toBeTruthy();
    await penpotOidcLogin(page, env.biberUsername, env.biberPassword);
  });
};
