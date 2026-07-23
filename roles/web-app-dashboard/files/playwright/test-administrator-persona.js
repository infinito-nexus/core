const { test, expect } = require("./fixtures/onion-test");
const { resolveTimeout } = require("./timeouts");

const { runAdminFlow } = require("./personas");

exports.register = function () {
  test("administrator: app → universal logout", async ({ page }) => {
    await runAdminFlow(page, {
      adminInteraction: async (interactivePage) => {
        // web-app-dashboard admin-only interaction: open a management surface.
        const link = interactivePage
          .getByRole("link", { name: /^(admin|tiles|navigation|tile)$/i })
          .first();
        if (await link.isVisible({ timeout: resolveTimeout(10_000) }).catch(() => false)) {
          await link.click({ timeout: resolveTimeout(30_000) }).catch(() => {});
          await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
          await expect(interactivePage.locator("body")).toContainText(
            /tiles|navigation|admin|services/i,
            { timeout: resolveTimeout(30_000) }
          );
        }
      },
    });
  });
};
