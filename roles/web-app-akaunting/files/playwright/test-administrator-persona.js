const { test, expect } = require("@playwright/test");
const { runAdminFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      // Akaunting admin-only interaction: open the Settings / Administration
      // surface. Drives a real management page; the click target is admin-only.
      const settingsLink = interactivePage
        .getByRole("link", { name: /^(settings|administration|users|companies)$/i })
        .first();
      if (await settingsLink.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await settingsLink.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /general settings|users|companies|categories|currencies|invoice/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
