const { test, expect } = require("@playwright/test");

// Anonymous (logged-out) visitor reaches biber's friendica profile.
//
// Friendica's profile pages are public-by-design (federation discovery,
// foreign instance lookups, embeddable links). The oauth2-proxy ACL on
// the friendica vhost MUST whitelist `/profile/` so the catch-all SSO
// gate does not bounce anonymous visitors to Keycloak before they ever
// see the page. This test pins that whitelist contract.
//
// The friendica.user row for biber is materialised lazily on first LDAP
// bind, so before the anonymous fetch we walk biber through one full
// login (and immediately log out again) in an isolated context.

exports.register = function (shared) {
  test("friendica: anonymous visitor can view biber's public profile", async ({ browser }) => {
    shared.skipUnlessServiceEnabled("ldap");

    await shared.provisionBiberAccount(browser);

    const baseUrl = shared.trimmedBaseUrl();
    const profileUrl = `${baseUrl}/profile/${shared.env.biberUsername}`;

    // Fresh context — no cookies from the provisioning login above.
    const anonContext = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      const anonPage = await anonContext.newPage();
      const response = await anonPage.goto(profileUrl, { waitUntil: "domcontentloaded" });
      expect(response, `Expected a response for ${profileUrl}`).toBeTruthy();
      expect(
        response.status(),
        `Expected anonymous /profile/${shared.env.biberUsername} status < 400 (whitelist must skip oauth2-proxy)`
      ).toBeLessThan(400);

      // The page must STAY on the friendica host. If the oauth2-proxy
      // catch-all gated the route, the browser would now be at
      // Keycloak's auth URL with a `redirect_uri` query param.
      const finalHost = new URL(anonPage.url()).host;
      const expectedHost = new URL(baseUrl).host;
      expect(
        finalHost,
        `Expected to stay on ${expectedHost} for an anonymous profile view, ended up at ${anonPage.url()}`
      ).toBe(expectedHost);

      // Friendica's profile template renders the visited nick somewhere
      // on the page (vcard header / page title) for every theme.
      await expect(
        anonPage.locator("body"),
        `Expected biber's profile body to mention "${shared.env.biberUsername}"`
      ).toContainText(shared.env.biberUsername, { timeout: 30_000 });

      // No authenticated nav element. Anonymous viewers must not see
      // their own /logout link (frio / vier both attach it to the
      // topbar when authenticated).
      await expect(
        anonPage.locator("a[href*='/logout']"),
        "Anonymous profile view must not expose the authenticated /logout link"
      ).toHaveCount(0);
    } finally {
      await anonContext.close().catch(() => {});
    }
  });
};
