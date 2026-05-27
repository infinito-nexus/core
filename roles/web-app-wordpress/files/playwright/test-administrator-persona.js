const { test, expect } = require("@playwright/test");

const { runAdminFlow } = require("./personas");

exports.register = function () {
  test("administrator: app → universal logout", async ({ page }) => {
    await runAdminFlow(page, {
      adminInteraction: async (interactivePage) => {
        const link = interactivePage
          .getByRole("link", { name: /^(dashboard|users|posts|settings|appearance|plugins)$/i })
          .first();
        if (await link.isVisible({ timeout: 10_000 }).catch(() => false)) {
          await link.click().catch(() => {});
          await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
          await expect(interactivePage.locator("body")).toContainText(
            /dashboard|users|posts|settings|appearance|plugins/i,
            { timeout: 30_000 },
          );
        }
      },
    });
  });
};
