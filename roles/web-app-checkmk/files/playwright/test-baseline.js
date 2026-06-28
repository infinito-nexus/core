const { test, expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, normalizeBaseUrl, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.beforeEach(async ({ page }) => {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("Checkmk front surface is reachable under the canonical domain", async ({ page }) => {
  const response = await page.goto(`${appBaseUrl}/`);
  expect(response, "Expected a Checkmk front response").toBeTruthy();
  expect(response.status(), "Expected the Checkmk front status to be < 500").toBeLessThan(500);
});

// Persona scenarios. Bodies live in the shared helper
// roles/test-e2e-playwright/files/personas so every role's flow stays consistent.
// Checkmk is fronted by the oauth2-proxy gate; biber/administrator are reachable
// only when SSO is enabled (see PERSONA_*_BLOCKED in playwright.env.j2).

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → admin surface → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      // Checkmk admin-only surface: the Setup menu is admin-gated.
      const setup = interactivePage.getByRole("link", { name: /^setup$/i }).first();
      if (await setup.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await setup.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(/setup|hosts|services|checkmk/i, {
          timeout: 30_000,
        });
      }
    },
  });
});
