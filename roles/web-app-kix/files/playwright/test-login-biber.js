const { test } = require("@playwright/test");
const { withLdapGroupMember } = require("./personas");

exports.register = function (shared) {
  test("biber: granted web-app-kix-user via Keycloak, full login flow (KIX → OAuth2-proxy → Keycloak → KIX-LDAP login → KIX UI → universal logout)", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    shared.skipUnlessServiceEnabled("ldap");
    shared.expectKeycloakAdminEnv();

    await shared.withBiberInGroup(shared.env.kixUserGroupPath, () =>
      shared.runKixLoginLogoutFlow(page, shared.env.biberUsername, shared.env.biberPassword),
    );
  });

  test("biber: member of the KIX user role group in the directory signs in through the KIX-LDAP login → KIX UI → logout", async ({ page }) => {
    shared.skipUnlessServiceEnabled("ldap");
    shared.skipUnlessServiceDisabled("sso");

    await withLdapGroupMember(shared.env.userGroupDn, shared.env.biberDn, () =>
      shared.runKixDirectoryLoginLogoutFlow(page, shared.env.biberUsername, shared.env.biberPassword),
    );
  });
};
