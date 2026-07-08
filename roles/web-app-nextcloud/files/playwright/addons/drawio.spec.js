const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

test("addon drawio: app installed + enabled (registered in OC.appswebroots)", async ({ browser }) => {
  skipUnlessAddonEnabled("drawio");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloudWithRetry(page);

    await gotoOnion(page, new URL("apps/files/", shared.env.nextcloudBaseUrl).toString(), {
      waitUntil: "domcontentloaded",
      timeout: resolveTimeout(60_000),
    });
    await shared.dismissBlockingNextcloudModals(page, page);

    const enabled = await page.evaluate(() => {
      const oc = window.OC || {};
      const webroots = oc.appswebroots || (oc.appConfig && oc.appConfig.appswebroots) || {};
      return Object.prototype.hasOwnProperty.call(webroots, "drawio");
    });
    expect(
      enabled,
      "drawio must be installed + enabled (registered in OC.appswebroots); it integrates the .drawio editor into Files via a file action and exposes no standalone app route",
    ).toBe(true);

    await expect(
      page.locator('script[src*="/apps/drawio/"], link[href*="/apps/drawio/"]'),
      "the enabled drawio app must inject its own frontend bundle into the Files UI (proves the app is loaded, not merely listed)",
    ).not.toHaveCount(0);
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
