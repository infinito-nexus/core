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

require("./test-seaweedfs");
require("./test-design");
require("./test-rbac");


test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");

test.beforeEach(async ({ page }) => {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("Mastodon front page is served under canonical domain with TLS", async ({ page }) => {
  const response = await gotoOnion(page, `${appBaseUrl}/`);
  expect(response, "Expected Mastodon response").toBeTruthy();
  expect(response.status(), "Expected Mastodon front page status < 400").toBeLessThan(400);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the Mastodon URL`
  ).toBe(true);
  expectHstsWhenTls(await ownResponseHeaders(response), appBaseUrl, "Mastodon");
});

test("Mastodon returns HTML content under canonical domain", async ({ request }) => {
  const response = await request.get(`${appBaseUrl}/`, { timeout: resolveTimeout(30_000) });
  expect(response.status(), "Expected Mastodon front page status < 400").toBeLessThan(400);
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
      await interactivePage
        .getByRole("navigation", { name: /^\s*main\s*$/i })
        .getByRole("button", { name: /^\s*more\s*$/i })
        .click({ timeout: resolveTimeout(30_000) });
      const administration = interactivePage
        .getByRole("link", { name: /^\s*administration\s*$/i })
        .first();
      await expect(administration).toBeVisible({ timeout: resolveTimeout(30_000) });
      const [adminTab] = await Promise.all([
        interactivePage.context().waitForEvent("page"),
        administration.click({ timeout: resolveTimeout(30_000) }),
      ]);
      await adminTab.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
      await expect(adminTab).toHaveURL(/\/admin\/dashboard/, {
        timeout: resolveTimeout(30_000),
      });
      await adminTab.close();
    },
  });
});
