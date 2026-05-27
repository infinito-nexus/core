const { test, expect } = require("@playwright/test");

// Administrator follows biber on friendica.
//
// Exercises the local-instance follow path: the administrator logs in
// via the variant-appropriate flow (v0 double-login through Keycloak,
// v2 native /login form), opens biber's profile page, triggers the
// follow / connect action, and confirms biber appears in the
// administrator's contact list afterwards.
//
// Friendica's UI labels the action "Connect/Follow", "Follow" (English),
// or "Verbinden/Folgen" / "Folgen" (German), depending on theme + locale.
// The actual handler is `/contact/follow?url=<profile-url>`, which renders
// a confirmation form. POST-ing that form 302-redirects to
// `/contact/<numeric-id>` once friendica has persisted the local contact
// row — that redirect is what verifies the follow took effect. (The
// global /contact listing only shows approved follows by default and
// would skip the pending row even after a successful POST.)

exports.register = function (shared) {
  test("friendica: administrator can follow biber", async ({ browser }) => {
    shared.skipUnlessServiceEnabled("ldap");

    await shared.provisionBiberAccount(browser);

    const baseUrl = shared.trimmedBaseUrl();
    const login = shared.pickLoginPath();

    const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      const adminPage = await adminContext.newPage();
      await login(adminPage, shared.env.adminUsername, shared.env.adminPassword);

      // Drive the follow via friendica's documented HTTP entry point so
      // the test stays stable across themes and locales. Anchor links
      // labelled "Connect/Follow" on the profile page all resolve to the
      // same /contact/follow handler, which renders a confirmation form.
      const followEntryUrl = `${baseUrl}/contact/follow?url=${encodeURIComponent(`${baseUrl}/profile/${shared.env.biberUsername}`)}`;
      await adminPage.goto(followEntryUrl, { waitUntil: "domcontentloaded" });

      // Friendica's confirmation form has a unique submit element
      // (id="dfrn-request-submit-button", value="Submit request"). The
      // navbar search form appears earlier in the document so a generic
      // form.first() selector would hit the wrong target.
      const submitButton = adminPage.locator("#dfrn-request-submit-button");
      await submitButton.waitFor({ state: "visible", timeout: 60_000 });
      await Promise.all([
        adminPage.waitForLoadState("domcontentloaded"),
        submitButton.click(),
      ]);

      // A successful follow 302-redirects to /contact/<numeric-id> — the
      // detail page of the freshly-persisted local contact row.
      await expect
        .poll(() => adminPage.url(), {
          timeout: 60_000,
          message: "Expected /contact/follow POST to land on /contact/<id> after persisting biber as a contact",
        })
        .toMatch(/\/contact\/\d+(?:[/?#]|$)/);

      // The contact detail page renders biber's identity address (nick@host)
      // somewhere on the page; assert it as the canonical post-follow proof.
      const expectedHandle = `${shared.env.biberUsername}@${new URL(baseUrl).host}`;
      await expect(
        adminPage.locator("body"),
        `Expected biber's handle "${expectedHandle}" on /contact/<id> after follow`
      ).toContainText(expectedHandle, { timeout: 30_000 });
    } finally {
      await adminContext.close().catch(() => {});
    }
  });
};
