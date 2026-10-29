const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

test("app_api addon: the AppAPI app is enabled for the logged-in user", async ({ browser }) => {
  skipUnlessAddonEnabled("app_api");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const filesUrl = new URL("apps/files/", shared.env.nextcloudBaseUrl).toString();
    await gotoOnion(page, filesUrl, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
    await shared.dismissBlockingNextcloudModals(page, page);

    await expect(
      page.locator("#app-content, #app-content-vue, #app-navigation-vue").first(),
      "the Nextcloud Files app shell must render before reading the enabled apps",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const appApiEnabled = await page.evaluate(() => {
      const oc = window.OC || {};
      const webroots = oc.appswebroots || (oc.appConfig && oc.appConfig.appswebroots) || {};
      return Object.prototype.hasOwnProperty.call(webroots, "app_api");
    });
    expect(
      appApiEnabled,
      "app_api must be listed in OC.appswebroots, which Nextcloud fills with the enabled apps only: the MCP surface proxies through AppAPI, so the role keeps it enabled while mcp.enabled is true",
    ).toBe(true);
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
