const { test, expect } = require("./fixtures/onion-test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("dashboard iframe sync JavaScript responds to iframeLocationChange events", async ({ page }) => {
    shared.skipUnlessServiceEnabled("cdn");
    shared.skipUnlessServiceEnabled("matomo");

    await gotoOnion(page,"/");
    await shared.waitForDashboardReady(page);

    const iframeTargetUrl = `${shared.env.matomoBaseUrl}/?playwright-iframe-sync=1`;
    const messagePayload = { href: iframeTargetUrl, origin: new URL(iframeTargetUrl).origin };

    await expect
      .poll(async () => {
        await page.evaluate(({ href, origin }) => {
          window.dispatchEvent(new MessageEvent("message", {
            origin,
            data: { type: "iframeLocationChange", href },
          }));
        }, messagePayload);
        return page.evaluate(() => new URL(window.location.href).searchParams.get("iframe"));
      }, {
        timeout: resolveTimeout(15_000),
        message: "Expected dashboard iframe sync JavaScript to update the iframe query parameter",
      })
      .toBe(iframeTargetUrl);
  });
};
