const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { runAdminFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      const settingsLink = interactivePage
        .getByRole("link", { name: /^(settings|administration|users|federation|reports)$/i })
        .first();
      if (await settingsLink.isVisible({ timeout: resolveTimeout(10_000) }).catch(() => false)) {
        await settingsLink.click({ timeout: resolveTimeout(30_000) }).catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /site settings|users|federation|reports|library/i,
          { timeout: resolveTimeout(30_000) },
        );
      }
    },
  });
});
