const { test, expect } = require("@playwright/test");
const { isOnionTarget, resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");
const {
  brokerAccessJwt,
  collectAppViewResponses,
  expectNoFailures,
  expectNoLxmRejections,
  reachFollowingFeed,
  readPreferences,
  restorePreferences,
  waitForResponseTo,
} = require("./_appview");

exports.register = function (shared) {
  test("OIDC: social-app renders Following and Notifications without errorMessageView or lxm page errors", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    test.skip(
      isOnionTarget(),
      "social-app only boots after loading its age-assurance config from public.api.bsky.app, which a Tor-routed test browser cannot reliably reach",
    );
    test.setTimeout(resolveTimeout(900_000));

    const pageErrors = [];
    page.on("pageerror", (err) => pageErrors.push(err.message));
    const seen = collectAppViewResponses(page);
    const { pdsBaseUrl } = shared.env;

    await shared.loginThroughBroker(page);
    const accessJwt = await brokerAccessJwt(page);
    const preferences = await readPreferences(page.request, pdsBaseUrl, accessJwt);
    try {
      await waitForResponseTo(seen, "app.bsky.notification.listNotifications");
      await expectNoLxmRejections(seen, pageErrors);

      await reachFollowingFeed(page);
      await waitForResponseTo(seen, "app.bsky.feed.getTimeline");
      await expectNoFailures(seen, "app.bsky.feed.getTimeline");
      const following = page.getByTestId("followingFeedPage");
      await expect(following.locator('[data-testid^="feedItem-by-"]').or(following.getByTestId("errorMessageView")).first()).toBeVisible({
        timeout: resolveTimeout(60_000),
      });
      await expect(following.getByTestId("errorMessageView"), "Following must render without an errorMessageView").toHaveCount(0);

      const notificationsFrom = seen.length;
      await gotoOnion(page, `${shared.env.baseUrl}/notifications`);
      const notifications = page.getByTestId("notificationsScreen");
      await expect(notifications).toBeVisible({ timeout: resolveTimeout(60_000) });
      await waitForResponseTo(seen, "app.bsky.notification.listNotifications", notificationsFrom);
      await expectNoFailures(seen, "app.bsky.notification.listNotifications");
      await expect(notifications.getByTestId("errorMessageView"), "Notifications must render without an errorMessageView").toHaveCount(0);

      await expectNoLxmRejections(seen, pageErrors);
    } finally {
      await restorePreferences(page.request, pdsBaseUrl, accessJwt, preferences);
    }
  });
};
