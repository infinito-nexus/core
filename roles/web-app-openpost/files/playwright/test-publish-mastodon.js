const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("administrator: connects the local Mastodon account through the OOB code flow and publishes to it", async ({ page, context }) => {
    shared.skipUnlessServiceEnabled("sso");
    shared.skipUnlessServiceEnabled("mastodon");
    shared.skipOnOnionSibling("mastodon");
    test.setTimeout(resolveTimeout(300_000)); // two Keycloak logins, Mastodon OAuth approval and the publishing worker round-trip
    const marker = `openpost-e2e ${Date.now()}`;

    await shared.signInViaOidc(page, shared.env.adminUsername, shared.env.adminPassword, "administrator");
    const account = await shared.connectMastodonAccount(page, context, "administrator");
    try {
      await shared.publishNow(page, account, marker);
      await expect
        .poll(() => shared.mastodonStatusExists(page, account, marker), {
          timeout: resolveTimeout(180_000),
          message: `administrator: expected "${marker}" on ${shared.env.mastodonBaseUrl}`,
        })
        .toBe(true);
    } finally {
      await shared.disconnectAccount(page, account).catch((error) => console.warn(`cleanup: ${error.message}`));
    }
    await shared.logout(page, "administrator");
  });
};
