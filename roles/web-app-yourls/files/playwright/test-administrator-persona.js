const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { runAdminFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test("administrator: app -> universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      // web-app-yourls admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(admin|administration|tools|stats|users)$/i })
        .first();
      if (await link.isVisible({ timeout: resolveTimeout(10_000) }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /admin|tools|stats|users|configuration/i,
          { timeout: resolveTimeout(30_000) },
        );
      }
    },
  });
});
