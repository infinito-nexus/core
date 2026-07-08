const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

test("external addon: admin External-sites settings panel renders", async ({ browser }) => {
  skipUnlessAddonEnabled("external");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const settingsUrl = new URL("settings/admin/external", shared.env.nextcloudBaseUrl).toString();
    await gotoOnion(page, settingsUrl, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
    await shared.dismissBlockingNextcloudModals(page, page);

    await expect(
      page.locator("#app-content, #app-content-vue, #content, #content-vue").first(),
      "the Nextcloud admin settings shell must render for the external app's own section (settings/admin/external)",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    await expect(
      page.locator("#external").first(),
      "the external app's own admin section (#external) must render (proves the 'external' section + template are served by the enabled app)",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    await expect(
      page.locator("#add_external_site").first(),
      "the external app's add-site admin control (#add_external_site) must render (proves the External-sites configuration UI is live)",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
