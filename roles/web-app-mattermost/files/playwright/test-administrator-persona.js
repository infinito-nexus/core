const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { runAdminFlow } = require("./personas");

exports.register = function () {
  test("administrator: app → universal logout", async ({ page }) => {
    await runAdminFlow(page, {
      adminInteraction: async (interactivePage) => {
        const link = interactivePage
          .getByRole("link", { name: /^(system console|admin|workspaces|teams|channels)$/i })
          .first();
        if (await link.isVisible({ timeout: resolveTimeout(10_000) }).catch(() => false)) {
          await link.click({ timeout: resolveTimeout(30_000) }).catch(() => {});
          await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
          await expect(interactivePage.locator("body")).toContainText(
            /system console|workspace|teams|channels|users|reporting/i,
            { timeout: resolveTimeout(30_000) },
          );
        }
      },
    });
  });
};
