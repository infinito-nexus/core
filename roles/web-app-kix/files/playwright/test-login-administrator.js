const { test, expect } = require("@playwright/test");

const { decodeDotenvQuotedValue } = require("./personas");

const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

exports.register = function (shared) {
  test("administrator: full login flow (KIX → OAuth2-proxy → Keycloak → KIX-LDAP login → KIX UI → universal logout)", async ({ page }) => {
    test.skip(!shared.env.oauth2Enabled, "OAuth2 shared service disabled");
    test.skip(!shared.env.ldapEnabled,   "LDAP shared service disabled");
    expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
    expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

    await shared.runKixLoginLogoutFlow(page, adminUsername, adminPassword);
  });
};
