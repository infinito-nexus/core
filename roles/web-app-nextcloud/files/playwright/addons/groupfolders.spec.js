const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("groupfolders addon: admin group-folders settings app mounts", async ({ browser }) => {
  skipUnlessAddonEnabled("groupfolders");
  test.setTimeout(120_000);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const settingsUrl = new URL("settings/admin/groupfolders", shared.env.nextcloudBaseUrl).toString();
    await page.goto(settingsUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
    await shared.dismissBlockingNextcloudModals(page, page);

    const groupfoldersApp = page
      .locator("#groupfolders-wrapper, #groupfolders-root")
      .or(page.getByRole("heading", { name: /^(group|team) folders$/i }));
    await expect(
      groupfoldersApp.first(),
      "the groupfolders admin app must mount (#groupfolders-wrapper/#groupfolders-root), proving the app is installed and enabled",
    ).toBeVisible({ timeout: 60_000 });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
