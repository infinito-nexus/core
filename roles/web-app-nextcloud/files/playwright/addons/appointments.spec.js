const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test("addon appointments: nextcloud app route renders", async ({ browser }) => {
  skipUnlessAddonEnabled("appointments");

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const appUrl = new URL("apps/appointments/", shared.env.nextcloudBaseUrl).toString();
    await page.goto(appUrl, { waitUntil: "commit", timeout: resolveTimeout(60_000) });

    const appContainer = page.locator(
      "#app-content, #app-content-vue, #content, #content-vue, .app-appointments"
    );
    await expect(appContainer.first()).toBeVisible({ timeout: resolveTimeout(60_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
