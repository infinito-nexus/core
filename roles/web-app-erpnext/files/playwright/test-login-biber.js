const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("biber: ERPNext OIDC login without an RBAC role grants no ERPNext role", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(180_000)); // OIDC round-trip plus the break-glass API read
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
    expect(shared.env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();

    await shared.signInViaErpnextOidc(page, shared.env.biberUsername, shared.env.biberPassword, "biber");

    const desk = await page.request.get(`${shared.env.erpnextBaseUrl}/desk`, {
      maxRedirects: 0,
      timeout: resolveTimeout(60_000),
    });
    expect(desk.status(), "a Keycloak user outside every ERPNext role group must not reach the desk").not.toBe(200);
    await shared.erpnextLogout(page);

    const api = await shared.breakGlassApi();
    try {
      const response = await api.get(
        `${shared.env.erpnextBaseUrl}/api/resource/User/${encodeURIComponent(shared.env.biberEmail)}`,
        { timeout: resolveTimeout(60_000) },
      );
      if (response.status() !== 404) {
        expect(response.status(), "reading biber's ERPNext user must succeed").toBe(200);
        const user = (await response.json()).data;
        expect(shared.env.managedRoles.length, "RBAC_MANAGED_ROLES_JSON must list the ERPNext roles of the RBAC groups").toBeGreaterThan(0);
        const held = (user.roles || []).map((row) => row.role).filter((role) => shared.env.managedRoles.includes(role));
        expect(held, "biber holds no RBAC role, so the reconcile and the sign-up gate must leave it without ERPNext roles").toEqual([]);
        expect(
          user.enabled,
          "an existing account outside every role group, however it was created, must be disabled by the deploy-time reconcile",
        ).toBe(0);
      }
    } finally {
      await api.dispose().catch(() => {});
    }
  });
};
