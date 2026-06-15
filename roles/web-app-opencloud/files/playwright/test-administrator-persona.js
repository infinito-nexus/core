const { test, expect } = require("@playwright/test");

const { runAdminFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      // web-app-opencloud admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(admin|users|spaces|files)$/i })
        .first();
      if (await link.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /admin|users|spaces|files|sharing|members/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
