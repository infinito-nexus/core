const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

// quota_warning emails/notifies users approaching their storage quota. It has
// no per-user app route; it registers a declarative ADMIN settings form (id
// "quota_warning", title "Quota warning") under section_id "additional", so its
// observable surface is the admin "Additional settings" page at
// settings/admin/additional — NOT settings/admin/quota_warning (no such admin
// section exists). Log in as administrator and assert that form renders there.
test("quota_warning addon: admin quota-warning settings form renders", async ({ browser }) => {
  skipUnlessAddonEnabled("quota_warning");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const settingsUrl = new URL("settings/admin/additional", shared.env.nextcloudBaseUrl).toString();
    await gotoOnion(page, settingsUrl, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
    await shared.dismissBlockingNextcloudModals(page, page);

    await expect(
      page.locator("#app-content, #app-content-vue, #content, #content-vue").first(),
      "the Nextcloud admin Additional settings page must render (quota_warning declares its form there)",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    await expect(
      page.getByText("Quota warning", { exact: true }).first(),
      "the quota_warning declarative admin settings form (section_id 'additional', title 'Quota warning') must render on settings/admin/additional",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
