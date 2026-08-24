const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

test("twofactor_nextcloud_notification addon: 2FA provider is enabled and offered in personal security settings", async ({ browser }) => {
  skipUnlessAddonEnabled("twofactor_nextcloud_notification");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const appsUrl = new URL("settings/apps/installed", shared.env.nextcloudBaseUrl).toString();
    await gotoOnion(page, appsUrl, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
    await shared.dismissBlockingNextcloudModals(page, page);

    await expect(
      page.locator("#app-content, #app-content-vue, #content, #content-vue").first(),
      "the Nextcloud installed-apps settings page must be visible",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const appEntry = page
      .locator(
        '#app-twofactor_nextcloud_notification, [data-id="twofactor_nextcloud_notification"], a[href*="twofactor_nextcloud_notification"]',
      )
      .first();

    await expect(
      appEntry,
      "the twofactor_nextcloud_notification app must appear as installed/enabled in the admin apps list",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const securityUrl = new URL("settings/user/security", shared.env.nextcloudBaseUrl).toString();
    const securityResponse = await gotoOnion(page, securityUrl, {
      waitUntil: "domcontentloaded",
      timeout: resolveTimeout(60_000),
    });
    await shared.dismissBlockingNextcloudModals(page, page);

    expect(
      securityResponse && securityResponse.status(),
      "the personal Security settings route must resolve",
    ).toBeLessThan(400);

    await expect(
      page.locator("#app-content, #app-content-vue, #content, #content-vue").first(),
      "the personal Security settings page must render",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const providerSurface = page
      .locator(
        '[data-provider-id="twofactor_nextcloud_notification"], '
          + '[id*="twofactor_nextcloud_notification"], '
          + 'section:has-text("Nextcloud notification"), '
          + 'fieldset:has-text("Nextcloud notification"), '
          + 'div:has-text("Two-Factor Authentication via Nextcloud notification")',
      )
      .first();

    await expect(
      providerSurface,
      "the Nextcloud-notification 2FA provider must be surfaced on the personal security settings page (its provider state is registered), proving the app is enabled and registered in the 2FA subsystem, not just installed",
    ).toBeAttached({ timeout: resolveTimeout(60_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
