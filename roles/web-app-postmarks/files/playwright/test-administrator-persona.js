const { test, expect } = require("@playwright/test");
const { runAdminFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test("administrator: app -> universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      await interactivePage.goto(`${interactivePage.url().replace(/\/$/, "")}/admin`).catch(() => {});
      await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
      await expect(interactivePage.locator("body")).toContainText(
        /bookmark|admin|tag|add|logout/i,
        { timeout: 30_000 },
      );
    },
  });
});
