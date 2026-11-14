const { test } = require("@playwright/test");

exports.register = function (shared) {
  test("administrator: KIX-LDAP login of the administrator role member → KIX UI → logout", async ({ page }) => {
    shared.skipUnlessServiceEnabled("ldap");

    await shared.runKixLdapLoginLogoutFlow(page, shared.env.adminUsername, shared.env.adminPassword);
  });
};
