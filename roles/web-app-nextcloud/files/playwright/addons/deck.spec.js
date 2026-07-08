const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test("addon deck: app is enabled and its board route renders", async ({ browser }) => {
  skipUnlessAddonEnabled("deck");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    // ENABLED SIGNAL: /apps/deck/ only resolves when the app is installed AND
    // enabled; a disabled/missing app redirects or 404s. The board shell
    // rendering is the app's own positive proof of being enabled.
    const appUrl = new URL("apps/deck/", shared.env.nextcloudBaseUrl).toString();
    await page.goto(appUrl, { waitUntil: "commit", timeout: resolveTimeout(60_000) });
    await shared.dismissBlockingNextcloudModals(page, page);

    const appContainer = page.locator(
      "#app-content, #app-content-vue, #content, #content-vue, .app-deck"
    );
    await expect(
      appContainer.first(),
      "the Deck app shell must render (app installed + enabled)",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
