const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const {
  expectHstsWhenTls,
  ownResponseHeaders,
  gotoOnion,
  normalizeBaseUrl,
  requireDotenvValue,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
} = require("./personas");
test.use({ ignoreHTTPSErrors: true });

require("./test-mcp-guest").register();
require("./test-design").register();
require("./test-rbac-gate").register();

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");

test.beforeEach(async ({ page }) => {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("Listmonk front page is served under canonical domain with TLS", async ({ page }) => {
  const response = await gotoOnion(page, `${appBaseUrl}/`);
  expect(response, "Expected Listmonk response").toBeTruthy();
  expect(response.status(), "Expected Listmonk front page status < 400").toBeLessThan(400);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the Listmonk URL`
  ).toBe(true);
  expectHstsWhenTls(await ownResponseHeaders(response), appBaseUrl, "Listmonk");
});

test("Listmonk returns HTML content under canonical domain", async ({ request }) => {
  const response = await request.get(`${appBaseUrl}/`, { timeout: resolveTimeout(30_000) });
  expect(response.status(), "Expected Listmonk front page status < 400").toBeLessThan(400);
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
      const menu = interactivePage.locator(".b-sidebar .menu-list");
      const settingsGroup = menu.locator("li > a[data-cy='settings']");
      await expect(
        settingsGroup,
        "the administration sidebar offers the admin-only settings group",
      ).toBeVisible({ timeout: resolveTimeout(30_000) });
      await settingsGroup.click({ timeout: resolveTimeout(30_000) });
      const logsEntry = menu.locator("ul a[data-cy='logs']");
      await expect(
        logsEntry,
        "clicking the settings group expands its entries",
      ).toBeVisible({ timeout: resolveTimeout(30_000) });
      await logsEntry.click({ timeout: resolveTimeout(30_000) });
      await expect(interactivePage).toHaveURL(/\/admin\/settings\/logs(?:[?#]|$)/, {
        timeout: resolveTimeout(30_000),
      });
      await expect(
        interactivePage.locator(".log-view .lines .line").first(),
        "the administrator reads the server log the application serves to administrators only",
      ).toBeVisible({ timeout: resolveTimeout(30_000) });
    },
  });
});
