const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { runAdminFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test("administrator: app -> universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      const link = interactivePage.getByRole("link", { name: /^tools$/i }).first();
      await expect(link).toBeVisible({ timeout: resolveTimeout(30_000) });
      await link.click({ timeout: resolveTimeout(30_000) });
      await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
      await expect(interactivePage).toHaveURL(/\/admin\/tools\.php/, {
        timeout: resolveTimeout(30_000),
      });
    },
  });
});
