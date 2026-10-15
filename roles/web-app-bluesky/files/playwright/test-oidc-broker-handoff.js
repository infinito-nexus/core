const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("OIDC: oauth2-proxy + login-broker drop a Bluesky session into social-app via Keycloak (variant A+)", async ({ page }) => {
    // The user-facing entry point at `web.bluesky.<domain>/` is gated
    // by the project's oauth2-proxy sidecar. Visiting the root while
    // unauthenticated MUST trigger an OIDC redirect to the realm's
    // authorization endpoint. After Keycloak login the request flows
    // through oauth2-proxy to the in-role login-broker, which (a)
    // auto-provisions the PDS account on first visit, (b) decrypts the
    // AES-256-GCM-encrypted app-password from the user's Keycloak
    // attribute, (c) creates a PDS session via createSession, and (d)
    // renders an HTML handoff page that drops the session JWTs into
    // localStorage["BSKY_STORAGE"] before redirecting to "/" — at which
    // point the social-app is reached as an authenticated Bluesky user
    // without ever showing the synthesised app-password to the
    // browser.
    shared.skipUnlessServiceEnabled("sso");
    await shared.loginThroughBroker(page);

    // The broker writes a schema-compliant `BSKY_STORAGE` payload
    // built from upstream `social-app@1.121.0`'s persisted defaults
    // PLUS the PDS session JWTs. Verify both that the entry exists
    // and that it carries an `accessJwt` — the latter is the only
    // observable proof that the broker's PDS createSession completed
    // and the handoff actually flowed through.
    const storageProbe = await page.evaluate(() => {
      const raw = localStorage.getItem("BSKY_STORAGE");
      if (!raw) return { present: false };
      try {
        const parsed = JSON.parse(raw);
        const cur = parsed && parsed.session && parsed.session.currentAccount;
        return {
          present: true,
          hasCurrentAccount: !!cur,
          hasAccessJwt: !!(cur && cur.accessJwt),
        };
      } catch {
        return { present: true, hasCurrentAccount: false, hasAccessJwt: false, parseError: true };
      }
    });
    expect(storageProbe.present, `BSKY_STORAGE missing — handoff never reached the browser. Probe: ${JSON.stringify(storageProbe)}`).toBe(true);
    expect(storageProbe.hasAccessJwt, `BSKY_STORAGE has no accessJwt — broker rendered the page but PDS createSession did not feed a usable session. Probe: ${JSON.stringify(storageProbe)}`).toBe(true);
  });
};
