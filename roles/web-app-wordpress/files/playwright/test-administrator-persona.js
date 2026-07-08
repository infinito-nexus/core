const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { runAdminFlow } = require("./personas");

exports.register = function () {
  test("administrator: app → universal logout", async ({ page }) => {
    await runAdminFlow(page, {
      adminInteraction: async (interactivePage) => {
        const link = interactivePage
          .getByRole("link", { name: /^(dashboard|users|posts|settings|appearance|plugins)$/i })
          .first();
        if (await link.isVisible({ timeout: resolveTimeout(10_000) }).catch(() => false)) {
          await link.click().catch(() => {});
          await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
          await expect(interactivePage.locator("body")).toContainText(
            /dashboard|users|posts|settings|appearance|plugins/i,
            { timeout: resolveTimeout(30_000) },
          );
        }
      },
    });
  });
};
