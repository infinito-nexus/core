const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

test("addon collectives: nextcloud app route renders", async ({ browser }) => {
  skipUnlessAddonEnabled("collectives");

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const appUrl = new URL("apps/collectives/", shared.env.nextcloudBaseUrl).toString();
    await gotoOnion(page, appUrl, { waitUntil: "commit", timeout: resolveTimeout(60_000) });

    const appContainer = page.locator(
      "#app-content, #app-content-vue, #content, #content-vue, .app-collectives"
    );
    await expect(appContainer.first()).toBeVisible({ timeout: resolveTimeout(60_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
