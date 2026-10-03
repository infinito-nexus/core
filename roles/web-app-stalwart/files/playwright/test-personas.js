const { test, expect } = require("@playwright/test");

const { runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
const { resolveTimeout } = require("./timeouts");

// Shared persona flows (gated by PERSONA_*_BLOCKED in templates/playwright.env.j2).
test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      const link = interactivePage
        .getByRole("link", { name: /^(domains|accounts|directory|settings|dashboard)$/i })
        .first();
      if (await link.isVisible().catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /domains|accounts|directory|settings|dashboard/i,
          { timeout: resolveTimeout(30_000) },
        );
      }
    },
  });
});
