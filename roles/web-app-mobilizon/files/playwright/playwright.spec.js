const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, normalizeBaseUrl, runAdminFlow, runBiberFlow, runGuestFlow , expectHstsWhenTls, gotoOnion } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.beforeEach(async ({ page }) => {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("Mobilizon front page is served under canonical domain with TLS", async ({ page }) => {
  const response = await gotoOnion(page, `${appBaseUrl}/`);
  expect(response, "Expected Mobilizon response").toBeTruthy();
  expect(response.status(), "Expected Mobilizon front page status < 400").toBeLessThan(400);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the Mobilizon URL`
  ).toBe(true);
  const headers = response.headers();
  expectHstsWhenTls(headers, appBaseUrl, "Mobilizon");
});

test("Mobilizon returns HTML content under canonical domain", async ({ request }) => {
  const response = await request.get(`${appBaseUrl}/`, { timeout: resolveTimeout(30_000) });
  expect(response.status(), "Expected Mobilizon front page status < 400").toBeLessThan(400);
  const contentType = response.headers()["content-type"] || "";
  expect(
    contentType.includes("text/html"),
    `Expected HTML content-type, got "${contentType}"`
  ).toBe(true);
});

// Persona scenarios.
// Bodies live in the shared helper roles/test-e2e-playwright/files/personas
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
      // web-app-mobilizon admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(events|groups|profile|admin)$/i })
        .first();
      if (await link.isVisible({ timeout: resolveTimeout(10_000) }).catch(() => false)) {
        await link.click({ timeout: resolveTimeout(30_000) }).catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /event|group|profile|mobilizon/i,
          { timeout: resolveTimeout(30_000) },
        );
      }
    },
  });
});
