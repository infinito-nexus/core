const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { skipUnlessServiceEnabled } = require("./service-gating");

const {
  assertCspResponseHeader,
  expectHstsWhenTls,
  gotoOnion,
  normalizeBaseUrl,
  requireDotenvValue,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
} = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
const apiBaseUrl = normalizeBaseUrl(process.env.API_BASE_URL || "");

test.beforeEach(async ({ page }) => {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("meta front page is served under canonical domain with TLS", async ({ page }) => {
  const response = await gotoOnion(page, `${appBaseUrl}/`);
  expect(response, "Expected meta response").toBeTruthy();
  expect(response.status(), "Expected meta front page status < 400").toBeLessThan(400);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the meta URL`
  ).toBe(true);
  const headers = response.headers();
  expectHstsWhenTls(headers, appBaseUrl, "meta");
});

test("meta returns HTML content under canonical domain", async ({ request }) => {
  const response = await request.get(`${appBaseUrl}/`, { timeout: resolveTimeout(30_000) });
  expect(response.status(), "Expected meta front page status < 400").toBeLessThan(400);
  const contentType = response.headers()["content-type"] || "";
  expect(
    contentType.includes("text/html"),
    `Expected HTML content-type, got "${contentType}"`
  ).toBe(true);
});

test("meta may read the API: its CSP connects to the API origin", async ({ request }) => {
  skipUnlessServiceEnabled("api");
  expect(apiBaseUrl, "API_BASE_URL must be set").toBeTruthy();
  const response = await request.get(`${appBaseUrl}/`, { timeout: resolveTimeout(30_000) });
  const directives = assertCspResponseHeader(response, "meta");
  expect(directives["connect-src"], "Expected connect-src to admit the API origin").toContain(new URL(apiBaseUrl).origin);
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
      const link = interactivePage
        .getByRole("link", { name: /^(admin|content|configuration|menu)$/i })
        .first();
      if (await link.isVisible().catch(() => false)) {
        await link.click({ timeout: resolveTimeout(30_000) }).catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /admin|content|configuration|menu|article|page/i,
          { timeout: resolveTimeout(30_000) },
        );
      }
    },
  });
});
