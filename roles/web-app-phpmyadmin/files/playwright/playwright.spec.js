const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const {
  expectHstsWhenTls,
  gotoOnion,
  ownResponseHeaders,
  normalizeBaseUrl,
  requireDotenvValue,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
} = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");

test.beforeEach(async ({ page }) => {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

require("./test-design").register();

test("phpMyAdmin front page is served under canonical domain with TLS", async ({ page }) => {
  const response = await gotoOnion(page, `${appBaseUrl}/`);
  expect(response, "Expected phpMyAdmin response").toBeTruthy();
  expect(response.status(), "Expected phpMyAdmin front page status < 400").toBeLessThan(400);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the phpMyAdmin URL`
  ).toBe(true);
  expectHstsWhenTls(await ownResponseHeaders(response), appBaseUrl, "phpMyAdmin");
});

test("phpMyAdmin returns HTML content under canonical domain", async ({ request }) => {
  const response = await request.get(`${appBaseUrl}/`, { timeout: resolveTimeout(30_000) });
  expect(response.status(), "Expected phpMyAdmin front page status < 400").toBeLessThan(400);
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
      const link = interactivePage.locator('#topmenu a[href*="route=/server/privileges"]').first();
      await expect(link).toBeVisible({ timeout: resolveTimeout(30_000) });
      await link.click({ timeout: resolveTimeout(30_000) });
      await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
      await expect(interactivePage).toHaveURL(/route=\/server\/privileges/, {
        timeout: resolveTimeout(30_000),
      });
    },
  });
});
