const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

test("addon cospend: nextcloud app route renders", async ({ browser }) => {
  skipUnlessAddonEnabled("cospend");

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const appUrl = new URL("apps/cospend/", shared.env.nextcloudBaseUrl).toString();
    await gotoOnion(page, appUrl, { waitUntil: "commit", timeout: resolveTimeout(60_000) });

    const appContainer = page.locator(
      "#app-content, #app-content-vue, #content, #content-vue, .app-cospend"
    );
    await expect(appContainer.first()).toBeVisible({ timeout: resolveTimeout(60_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
