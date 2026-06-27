const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("biber (ldap): n8n sign-in form authenticates against svc-db-openldap", async ({ page }) => {
    shared.skipUnlessServiceEnabled("ldap");
    if (shared.env.oidcEnabled) {
      test.skip(true, "OIDC also enabled — LDAP-form login only exercised in LDAP-only variant (V3)");
    }
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

    await shared.signInViaN8nLdap(page, shared.env.biberUsername, shared.env.biberPassword);

    await expect(page.locator("body")).toContainText(
      /workflow|execution|credential|canvas|overview/i,
      { timeout: 60_000 }
    );

    await shared.n8nLogout(page);
  });
};
