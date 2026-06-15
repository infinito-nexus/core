const { test, expect } = require("@playwright/test");
const { runAdminFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      // web-app-flowise admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(admin|api keys|chatflows|tools|credentials|users)$/i })
        .first();
      if (await link.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /api keys|chatflows|tools|credentials|users|workspaces?/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
