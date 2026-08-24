const { test } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

// Dedicated LDAP scenario per the playwright contract: when both OIDC and LDAP
// are enabled, each persona's primary login path uses OIDC, and each persona
// MUST additionally execute an LDAP-bound scenario. In V1 Keycloak federates
// OpenLDAP via the LDAP provider, so the form login still hits Keycloak's UI
// but the user record resolves through the LDAP backend.
exports.register = function (shared) {
  test("biber: ldap-bound login through keycloak", async ({ page }) => {
    shared.skipUnlessServiceEnabled("ldap");
    test.setTimeout(resolveTimeout(180_000));
    await shared.runBiberFlow(page, {
      biberInteraction: async (p) => {
        await shared.reachJitsiPrejoin(p, "biber", "biber-ldap-room");
      },
    });
  });

  test("administrator: ldap-bound login through keycloak", async ({ page }) => {
    shared.skipUnlessServiceEnabled("ldap");
    test.setTimeout(resolveTimeout(180_000));
    await shared.runAdminFlow(page, {
      adminInteraction: async (p) => {
        await shared.reachJitsiPrejoin(p, "admin", "admin-ldap-room");
        await shared.openJitsiSettingsPanel(p, "administrator");
      },
    });
  });
};
