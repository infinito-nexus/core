const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("dashboard iframe sync JavaScript responds to iframeLocationChange events", async ({ page }) => {
    shared.skipUnlessServiceEnabled("cdn");
    shared.skipUnlessServiceEnabled("matomo");

    await page.goto("/");
    await shared.waitForDashboardReady(page);

    const iframeTargetUrl = `${shared.env.matomoBaseUrl}/?playwright-iframe-sync=1`;
    await page.evaluate(({ href, origin }) => {
      window.dispatchEvent(new MessageEvent("message", {
        origin,
        data: { type: "iframeLocationChange", href },
      }));
    }, { href: iframeTargetUrl, origin: new URL(iframeTargetUrl).origin });

    await expect
      .poll(() => page.evaluate(() => new URL(window.location.href).searchParams.get("iframe")), {
        timeout: 10_000,
        message: "Expected dashboard iframe sync JavaScript to update the iframe query parameter",
      })
      .toBe(iframeTargetUrl);
  });
};
