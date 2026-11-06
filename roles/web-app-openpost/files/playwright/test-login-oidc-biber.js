const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("biber: Keycloak login opens the composer but never the organisation workspace", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(120_000)); // OIDC round-trip via Keycloak plus just-in-time provisioning
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

    await shared.signInViaOidc(page, shared.env.biberUsername, shared.env.biberPassword, "biber");
    await shared.openComposer(page, "biber");
    await shared.assertWorkspaceHidden(page, shared.env.organisationWorkspace, "biber");
    await shared.assertInstanceAdministrationDenied(page, "biber");
    await shared.logout(page, "biber");
  });
};
