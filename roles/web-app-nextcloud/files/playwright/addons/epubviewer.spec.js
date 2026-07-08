const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("addon epubviewer: EPUB reader personal settings panel renders and reflects config", async ({ browser }) => {
  skipUnlessAddonEnabled("epubviewer");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloudWithRetry(page);

    const settingsUrl = new URL("settings/user/epubviewer", shared.env.nextcloudBaseUrl).toString();
    const response = await page.goto(settingsUrl, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
    expect(
      response === null || response.status() !== 404,
      "the epubviewer app must register its settings/user/epubviewer section (app installed + enabled)",
    ).toBeTruthy();
    await shared.dismissBlockingNextcloudModals(page, page);

    await expect(
      page.locator("#reader-personal").first(),
      "the epubviewer app must render its own EPUB reader personal settings panel",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    await expect(
      page.locator("#EpubEnable").first(),
      "the EPUB-enable checkbox must reflect the persisted epubviewer user config",
    ).toBeChecked({ timeout: resolveTimeout(60_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
