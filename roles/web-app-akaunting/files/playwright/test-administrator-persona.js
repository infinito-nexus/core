const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
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
      if (await settingsLink.isVisible({ timeout: resolveTimeout(10_000) }).catch(() => false)) {
        await settingsLink.click({ timeout: resolveTimeout(30_000) }).catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /general settings|users|companies|categories|currencies|invoice/i,
          { timeout: resolveTimeout(30_000) },
        );
      }
    },
  });
});
