const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

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
    const { baseUrl, oidcIssuerUrl, adminUsername, adminPassword } = shared.env;
    expect(adminUsername, "ADMIN_USERNAME must be set when OIDC is enabled").toBeTruthy();
    expect(adminPassword, "ADMIN_PASSWORD must be set when OIDC is enabled").toBeTruthy();
    expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set when OIDC is enabled").toBeTruthy();

    const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
    const expectedBaseUrl = baseUrl.replace(/\/$/, "");

    await page.goto(`${expectedBaseUrl}/`);

    await expect
      .poll(() => page.url(), {
        timeout: resolveTimeout(60_000),
        message: `expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`,
      })
      .toContain(expectedOidcAuthUrl);

    await shared.performKeycloakLoginForm(page, adminUsername, adminPassword);

    // Wait for the post-OIDC redirect chain to settle. After Keycloak
    // accepts the credentials, the browser bounces through
    //   /oauth2/callback → / → broker handoff → social-app
    // and we want the URL to come to rest on the Bluesky base URL —
    // NOT on an `/oauth2/*` path. The `expect.poll` form alone matches
    // any URL containing the base, including the intermediate
    // `/oauth2/start` redirect, so we additionally pin the path to
    // not be under `/oauth2/`.
    await expect
      .poll(() => page.url(), {
        timeout: resolveTimeout(90_000),
        message: `expected post-OIDC URL to land on Bluesky outside /oauth2/* (got: ${page.url()})`,
      })
      .toMatch(new RegExp(`^${expectedBaseUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/(?!oauth2/)`));

    // Wait for the network to settle so the broker's handoff JS can
    // commit localStorage + cookie before we inspect them.
    await page.waitForLoadState("networkidle", { timeout: resolveTimeout(30_000) }).catch(() => {});
    await expect(page.locator("body")).toBeVisible({ timeout: resolveTimeout(60_000) });

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
