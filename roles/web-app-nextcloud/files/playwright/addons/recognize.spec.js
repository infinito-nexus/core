const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("recognize addon: admin recognize settings UI mounts its own surface", async ({ browser }) => {
  skipUnlessAddonEnabled("recognize");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const settingsUrl = new URL("settings/admin/recognize", shared.env.nextcloudBaseUrl).toString();
    await page.goto(settingsUrl, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
    await shared.dismissBlockingNextcloudModals(page, page);

    const recognizeRoot = page.locator("#recognize");
    await expect(
      recognizeRoot,
      "the recognize admin settings Vue component (#recognize) must mount (app installed + enabled)",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    await expect(
      recognizeRoot.getByText(/Face recognition/i).first(),
      "recognize's own settings sections (e.g. Face recognition) must render inside #recognize",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
