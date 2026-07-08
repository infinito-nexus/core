const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  // hooks.js (EXTERNAL_HOOK_FILES) auto-provisions ANY Keycloak identity
  // forwarded via the trusted Remote-Email header as a `global:member` n8n
  // user — not just the owner account tasks/02_bootstrap.yml creates. So
  // biber, a non-admin persona with no pre-existing n8n-local account, now
  // reaches n8n's authenticated workflow surface too, exactly like the
  // administrator.
  test("biber: Keycloak SSO auto-provisions and lands on the workflow editor", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
    expect(shared.env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();

    await shared.signInViaN8nOidc(page, shared.env.biberUsername, shared.env.biberPassword, "biber");

    await expect(page.locator("body")).toContainText(
      /workflow|execution|credential|canvas|overview/i,
      { timeout: 60_000 }
    );

    await shared.n8nLogout(page);
  });
};
