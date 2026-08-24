const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

test("addon mail: app route renders the Nextcloud app container", async ({ browser }) => {
  skipUnlessAddonEnabled("mail");

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const appUrl = new URL("apps/mail/", shared.env.nextcloudBaseUrl).toString();
    await gotoOnion(page, appUrl, { waitUntil: "commit", timeout: resolveTimeout(60_000) });

    await expect(
      page.locator("#app-content, #app-content-vue, #content").first()
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
  } finally {
    await page.close();
    await context.close();
  }
});
