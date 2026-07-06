const { test, expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, normalizeBaseUrl, runAdminFlow, runBiberFlow, runGuestFlow , expectHstsWhenTls } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.beforeEach(async ({ page }) => {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("LAM front page is served under canonical domain with TLS", async ({ page }) => {
  const response = await page.goto(`${appBaseUrl}/`);
  expect(response, "Expected LAM response").toBeTruthy();
  expect(response.status(), "Expected LAM front page status < 400").toBeLessThan(400);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the LAM URL`
  ).toBe(true);
  const headers = response.headers();
  expectHstsWhenTls(headers, appBaseUrl, "LAM");
});

test("LAM returns HTML content under canonical domain", async ({ request }) => {
  const response = await request.get(`${appBaseUrl}/`);
  expect(response.status(), "Expected LAM front page status < 400").toBeLessThan(400);
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
      // web-app-lam admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(users|groups|tools|admin)$/i })
        .first();
      if (await link.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /user|group|tools|configuration|ldap|account/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
