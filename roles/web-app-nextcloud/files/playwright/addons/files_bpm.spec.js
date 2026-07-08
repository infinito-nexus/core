const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("files_bpm addon: BPMN editor route renders the modeler canvas", async ({ browser }) => {
  skipUnlessAddonEnabled("files_bpm");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const appUrl = new URL("apps/files_bpm/", shared.env.nextcloudBaseUrl).toString();
    const response = await page.goto(appUrl, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
    expect(
      response === null || response.status() !== 404,
      "the files_bpm app must serve its apps/files_bpm/ modeler route (app installed + enabled)",
    ).toBeTruthy();
    await shared.dismissBlockingNextcloudModals(page, page);

    await expect(
      page.locator("#bpmn-app").first(),
      "the files_bpm app must render its own BPMN modeler surface (#bpmn-app)",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
