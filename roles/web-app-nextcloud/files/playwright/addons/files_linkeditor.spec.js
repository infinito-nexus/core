const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

test("files_linkeditor addon: Files New menu exposes the link-editor create entries", async ({ browser }) => {
  skipUnlessAddonEnabled("files_linkeditor");
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
      "the Nextcloud Files app content must be visible before opening its New menu",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const newMenuButton = page.getByRole("button", { name: "New", exact: true });
    await expect(
      newMenuButton,
      "the Files app must expose its New file-creation menu button",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    // The firstrunwizard "what's new" modal mounts with the Files app, after the
    // post-goto dismissal ran, and overlays the New button so the click is
    // swallowed. Re-dismiss once the app has rendered, before driving the menu.
    await shared.dismissBlockingNextcloudModals(page, page);
    await newMenuButton.click();

    await expect(
      page.getByRole("menuitem", { name: "New link (.URL)" }),
      "files_linkeditor must register its 'New link (.URL)' entry in the Files New menu",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    await expect(
      page.getByRole("menuitem", { name: "New link (.webloc)" }),
      "files_linkeditor must register its 'New link (.webloc)' entry in the Files New menu",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
