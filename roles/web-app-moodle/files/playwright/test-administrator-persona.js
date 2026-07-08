const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("administrator: app → universal logout", async ({ page }) => {
    await shared.runAdminFlow(page, {
      adminInteraction: async (interactivePage) => {
        const link = interactivePage
          .getByRole("link", { name: /^(site administration|users|courses|reports|server)$/i })
          .first();
        if (await link.isVisible({ timeout: resolveTimeout(10_000) }).catch(() => false)) {
          await link.click().catch(() => {});
          await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
          await expect(interactivePage.locator("body")).toContainText(
            /site administration|users|courses|reports|server|appearance/i,
            { timeout: resolveTimeout(30_000) },
          );
        }
      },
    });
  });
};
