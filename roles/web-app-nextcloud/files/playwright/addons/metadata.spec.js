const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("metadata addon: Files app loads the metadata app's own provider bundle", async ({ browser }) => {
  skipUnlessAddonEnabled("metadata");
  test.setTimeout(120_000);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const filesUrl = new URL("apps/files/", shared.env.nextcloudBaseUrl).toString();
    await page.goto(filesUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
    await shared.dismissBlockingNextcloudModals(page, page);

    await expect(
      page.locator("#app-content, #app-content-vue, #app-navigation-vue").first(),
      "the Nextcloud Files app shell must render before checking the metadata provider",
    ).toBeVisible({ timeout: 60_000 });

    const metadataEnabled = await page.evaluate(() => {
      const oc = window.OC || {};
      const webroots = oc.appswebroots || (oc.appConfig && oc.appConfig.appswebroots) || {};
      return Object.prototype.hasOwnProperty.call(webroots, "metadata");
    });
    expect(
      metadataEnabled,
      "the metadata app must be registered in OC.appswebroots for the logged-in user: this is populated only when the metadata app is installed AND enabled, so a disabled/broken app fails here",
    ).toBe(true);

    await expect(
      page.locator('script[src*="apps/metadata/"]'),
      "the metadata app's own frontend bundle must be injected into the Files page (apps/metadata/...), proving the metadata provider is actually loaded and coupled to Files, not just listed as available",
    ).not.toHaveCount(0, { timeout: 30_000 });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
