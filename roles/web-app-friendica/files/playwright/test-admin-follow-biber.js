const { test, expect } = require("@playwright/test");

// Administrator follows biber on friendica.
//
// Exercises the local-instance follow path: the administrator logs in
// via the variant-appropriate flow (v0 double-login through Keycloak,
// v2 native /login form), opens biber's follow confirmation form,
// submits it, and confirms biber is persisted as a local contact.
//
// The suite runs twice against one persistent instance (sync + async
// deploy passes), so the test first resets the relationship: a single
// GET to /contact/unfollow?auto=1&url=<profile> unfollows biber when
// already followed and is a harmless redirect otherwise. That keeps the
// follow action under test on every run instead of short-circuiting to
// friendica's "already added this contact" page on the second pass.
//
// The follow handler is `/contact/follow?url=<profile-url>`, which renders
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

      const biberProfileUrl = `${baseUrl}/profile/${shared.env.biberUsername}`;

      // Reset the relationship so the follow below always exercises the real
      // action. Friendica's Unfollow module performs the unfollow inline when
      // called with `auto=1` (redirecting to /contact/<id>) and simply
      // redirects back to /contact when biber is not currently followed.
      await adminPage.goto(
        `${baseUrl}/contact/unfollow?auto=1&url=${encodeURIComponent(biberProfileUrl)}`,
        { waitUntil: "domcontentloaded" }
      );

      // Drive the follow via friendica's documented HTTP entry point so the
      // test stays stable across themes and locales. Anchor links labelled
      // "Connect/Follow" on the profile page all resolve to this same
      // /contact/follow handler, which renders a confirmation form.
      await adminPage.goto(
        `${baseUrl}/contact/follow?url=${encodeURIComponent(biberProfileUrl)}`,
        { waitUntil: "domcontentloaded" }
      );

      // The confirmation form has a unique submit element
      // (id="dfrn-request-submit-button", value="Submit Request"). The navbar
      // search form appears earlier in the document so a generic form.first()
      // selector would hit the wrong target.
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
