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

test("Social Home front page is served under canonical domain with TLS", async ({ page }) => {
  const response = await gotoOnion(page, `${appBaseUrl}/`);
  expect(response, "Expected Social Home response").toBeTruthy();
  expect(response.status(), "Expected Social Home front page status < 400").toBeLessThan(400);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the Social Home URL`
  ).toBe(true);
  const headers = response.headers();
  expectHstsWhenTls(headers, appBaseUrl, "Social Home");
});

test("Social Home returns HTML content under canonical domain", async ({ request }) => {
  const response = await request.get(`${appBaseUrl}/`, { timeout: resolveTimeout(30_000) });
  expect(response.status(), "Expected Social Home front page status < 400").toBeLessThan(400);
  const contentType = response.headers()["content-type"] || "";
  expect(
    contentType.includes("text/html"),
    `Expected HTML content-type, got "${contentType}"`
  ).toBe(true);
});

test("Social Home reports subsystem health on /healthz", async ({ request }) => {
  const response = await request.get(`${appBaseUrl}/healthz`, { timeout: resolveTimeout(30_000) });
  expect(response.status(), "Expected /healthz to report healthy").toBe(200);
  const body = await response.json();
  expect(body.status, "Expected /healthz status ok").toBe("ok");
  expect(body.subsystems.db, "Expected the SQLite subsystem to answer SELECT 1").toBe("ok");
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
      const link = interactivePage
        .getByRole("link", { name: /^(feed|spaces|calendar|federation|admin)$/i })
        .first();
      if (await link.isVisible().catch(() => false)) {
        await link.click({ timeout: resolveTimeout(30_000) }).catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /feed|spaces|calendar|federation|admin/i,
          { timeout: resolveTimeout(30_000) },
        );
      }
    },
  });
});
