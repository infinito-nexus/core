const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  // biber has no n8n-local account (tasks/02_bootstrap.yml provisions only
  // the owner). n8n Community Edition does not accept oauth2-proxy's session
  // as its own, so biber cannot reach n8n's authenticated workflow surface at
  // all — only the SSO edge gate is in scope for a non-admin persona here.
  // This test proves the edge gate itself: after the Keycloak round-trip,
  // oauth2-proxy's internal auth-check endpoint MUST accept biber's session
  // (202), the same response nginx's `auth_request /oauth2/auth` relies on to
  // let the request through to n8n's own login form.
  test("biber: Keycloak SSO clears the oauth2-proxy edge gate", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
    expect(shared.env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();

    await shared.signInViaN8nOidc(page, shared.env.biberUsername, shared.env.biberPassword, "biber");

    const authCheck = await page.request.get(`${shared.env.n8nBaseUrl}/oauth2/auth`);
    expect(
      authCheck.status(),
      "expected oauth2-proxy to accept biber's Keycloak session (202)"
    ).toBe(202);

    await shared.n8nLogout(page);
  });
};
