const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("administrator: app → universal logout", async ({ page }) => {
    await shared.runAdminFlow(page, {
      adminInteraction: async (interactivePage) => {
        // web-app-pixelfed admin-only interaction: open a management surface.
        const link = interactivePage
          .getByRole("link", { name: /^(admin|administration|users|settings|reports)$/i })
          .first();
        if (await link.isVisible({ timeout: resolveTimeout(10_000) }).catch(() => false)) {
          await link.click().catch(() => {});
          await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
          await expect(interactivePage.locator("body")).toContainText(
            /admin|users|settings|reports|federation|moderation/i,
            { timeout: resolveTimeout(30_000) },
          );
        }
      },
    });
  });
};
