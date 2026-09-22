const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(async ({ page }) => {
  expect(shared.appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(shared.canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

require("./test-front-page").register(shared);
require("./test-versions").register(shared);
require("./test-on-demand-build").register(shared);
require("./test-languages").register(shared);

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      const link = interactivePage
        .getByRole("link", { name: /^(admin|build|configuration|projects)$/i })
        .first();
      if (await link.isVisible().catch(() => false)) {
        await link.click({ timeout: resolveTimeout(30_000) }).catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /admin|build|configuration|projects|index/i,
          { timeout: resolveTimeout(30_000) },
        );
      }
    },
  });
});
