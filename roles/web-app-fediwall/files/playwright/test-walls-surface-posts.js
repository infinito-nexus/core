const { test, expect } = require("@playwright/test");

// Cross-Fediverse scenario — runs whenever Mastodon AND Friendica are
// deployed alongside fediwall. The test is fully data-driven against
// each wall's `wall-config.json` `servers` list:
//
//   - biber posts a unique status to BOTH Mastodon and Friendica via
//     the same SSO/ldapauth UI flow a human would use (LDAP is the
//     single source of truth for biber's credentials; the local
//     accounts on Mastodon/Friendica come into existence lazily on
//     first SSO login, exactly as in production — no API auth, no
//     password duplication, no manual user provisioning).
//
//   - For every deployed wall, the test reads `wall-config.json`
//     and asserts: a sibling's post is visible iff that sibling's
//     domain is listed in `servers`; otherwise it MUST NOT appear.
//
// This single test covers both variants automatically:
//   variant 0 — one wall polling all active siblings (both posts visible)
//   variant 1 — two walls; one polls both siblings, the other only
//               Mastodon (friendica post must be absent there).

exports.register = function (shared) {
  test("each wall surfaces biber's posts according to its servers list", async ({
    browser,
    request,
  }) => {
    shared.skipUnlessServiceEnabled("mastodon");
    shared.skipUnlessServiceEnabled("friendica");

    const stamp = Date.now();
    // Driver per source app: how to post + which host the wall config
    // would list when this sibling is enabled.
    const siblings = [
      {
        name: "mastodon",
        host: shared.urlHost(shared.env.mastodonBaseUrl),
        status: `fediwall-e2e mastodon ${stamp}`,
        post: (page) => shared.postOnMastodonViaUi(page, shared.env.mastodonBaseUrl, `fediwall-e2e mastodon ${stamp}`),
      },
      {
        name: "friendica",
        host: shared.urlHost(shared.env.friendicaBaseUrl),
        status: `fediwall-e2e friendica ${stamp}`,
        post: (page) => shared.postOnFriendicaViaUi(page, shared.env.friendicaBaseUrl, `fediwall-e2e friendica ${stamp}`),
      },
    ];

    // Post once per sibling — isolated browser contexts so the OIDC
    // session for Mastodon and the ldapauth session for Friendica do
    // not bleed cookies/storage across.
    for (const s of siblings) {
      const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        await s.post(await ctx.newPage());
      } finally {
        await ctx.close().catch(() => {});
      }
    }

    // For every deployed wall: read its servers list and assert that
    // each sibling's post appears iff its host is in `servers`.
    for (const slug of shared.env.wallSlugs) {
      const cfgRes = await request.get(`${shared.env.appBaseUrl}/${slug}/wall-config.json`);
      expect(
        cfgRes.ok(),
        `wall-config.json for slug='${slug}' must be reachable`
      ).toBeTruthy();
      const cfg = await cfgRes.json();
      const wallHosts = new Set(cfg.servers || []);

      const wallCtx = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const wallPage = await wallCtx.newPage();
        for (const s of siblings) {
          const wallUrl = `${shared.env.appBaseUrl}/${slug}/`;
          if (wallHosts.has(s.host)) {
            await shared.expectPostVisibleOnWall(wallPage, wallUrl, s.status);
          } else {
            await shared.expectPostAbsentFromWall(wallPage, wallUrl, s.status);
          }
        }
      } finally {
        await wallCtx.close().catch(() => {});
      }
    }
  });
};
