const { test, expect } = require("@playwright/test");
const { runAdminFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      // web-app-joomla admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(administrator|users|content|menus|extensions|configuration)$/i })
        .first();
      if (await link.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /users|content|menus|extensions|configuration|articles/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
