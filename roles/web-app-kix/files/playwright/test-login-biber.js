const { test } = require("@playwright/test");

exports.register = function (shared) {
  test("biber: member of the KIX user role group in the directory signs in through the KIX-LDAP login → KIX UI → logout", async ({ page }) => {
    shared.skipUnlessServiceEnabled("ldap");

    await shared.withBiberInKixUserGroup(() =>
      shared.runKixLdapLoginLogoutFlow(page, shared.env.biberUsername, shared.env.biberPassword),
    );
  });
};
