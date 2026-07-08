const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { runAdminFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      // web-app-opentalk admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(admin|administration|rooms|users|invites)$/i })
        .first();
      if (await link.isVisible({ timeout: resolveTimeout(10_000) }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /admin|rooms|users|invites|reports|administration/i,
          { timeout: resolveTimeout(30_000) },
        );
      }
    },
  });
});
