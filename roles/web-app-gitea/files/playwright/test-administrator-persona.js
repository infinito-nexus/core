const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("administrator: app → universal logout", async ({ page }) => {
    await shared.runAdminFlow(page, {
      adminInteraction: async (interactivePage) => {
        // web-app-gitea admin-only interaction: open a management surface.
        const link = interactivePage
          .getByRole("link", { name: /^(site administration|admin|user accounts|repositories)$/i })
          .first();
        if (await link.isVisible({ timeout: 10_000 }).catch(() => false)) {
          await link.click().catch(() => {});
          await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
          await expect(interactivePage.locator("body")).toContainText(
            /site administration|repositories|users|integrations|actions/i,
            { timeout: 30_000 },
          );
        }
      },
    });
  });
};
