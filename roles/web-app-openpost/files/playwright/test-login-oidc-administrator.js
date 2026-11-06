const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("administrator: Keycloak login provisions an instance admin who reaches the instance administration", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(120_000)); // OIDC round-trip via Keycloak plus just-in-time provisioning
    expect(shared.env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

    await shared.signInViaOidc(page, shared.env.adminUsername, shared.env.adminPassword, "administrator");
    await shared.openInstanceAdministration(page, "administrator");
    await shared.logout(page, "administrator");
  });
};
