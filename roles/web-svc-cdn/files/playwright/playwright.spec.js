const { test, expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, normalizeBaseUrl, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const cdnBaseUrl = normalizeBaseUrl(process.env.CDN_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  expect(cdnBaseUrl, "CDN_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("cdn index is served under canonical domain with TLS", async ({ page }) => {
  const response = await page.goto(`${cdnBaseUrl}/`);
  expect(response, "Expected CDN index response").toBeTruthy();
  expect(response.status(), "Expected CDN index status < 400").toBeLessThan(400);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the CDN URL`
  ).toBe(true);
  const headers = response.headers();
  expect(headers["strict-transport-security"], "CDN must emit HSTS").toBeTruthy();
});

// Persona scenarios.
// Bodies live in the shared helper roles/test-e2e-playwright/files/personas.js
// so every role's persona flow stays consistent.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      // web-svc-cdn admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(admin|index|status)$/i })
        .first();
      if (await link.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /admin|status|index/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
