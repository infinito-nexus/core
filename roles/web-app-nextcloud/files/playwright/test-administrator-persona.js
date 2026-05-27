const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("administrator: app → universal logout", async ({ page }) => {
    await shared.runAdminFlow(page, {
      adminInteraction: async (interactivePage) => {
        // web-app-nextcloud admin-only interaction: open a management surface.
        const link = interactivePage
          .getByRole("link", { name: /^(administration settings|administration|users|apps|files)$/i })
          .first();
        if (await link.isVisible({ timeout: 10_000 }).catch(() => false)) {
          await link.click().catch(() => {});
          await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
          await expect(interactivePage.locator("body")).toContainText(
            /administration|users|apps|files|sharing|security/i,
            { timeout: 30_000 },
          );
        }
      },
    });
  });
};
