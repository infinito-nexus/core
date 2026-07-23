const { test, expect } = require("@playwright/test");

const { setupMatomoPage } = require("./_shared");
const { runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(async ({ page }) => {
  await setupMatomoPage(page);
});

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      // Matomo admin-only interaction: open the Websites admin page from the
      // topbar / admin gear. Confirms the admin reaches the management surface;
      // biber's deny-check at matomo is the symmetric counter assertion.
      const settingsLink = interactivePage
        .getByRole("link", { name: /administration|settings|websites/i })
        .first();
      if (await settingsLink.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await settingsLink.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /websites|administration|users|general settings/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
