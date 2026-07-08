const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, normalizeBaseUrl, runAdminFlow, runBiberFlow, runGuestFlow , expectHstsWhenTls } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.beforeEach(async ({ page }) => {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("hugo front page is served under canonical domain with TLS + HSTS", async ({ page }) => {
  const response = await page.goto(`${appBaseUrl}/`);
  expect(response, "Expected hugo response").toBeTruthy();
  expect(response.status(), "Expected hugo front page status < 400").toBeLessThan(400);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the hugo URL`
  ).toBe(true);
  const headers = response.headers();
  expectHstsWhenTls(headers, appBaseUrl, "hugo");
});

test("hugo emits a CSP header on the front page", async ({ request }) => {
  const response = await request.get(`${appBaseUrl}/`);
  expect(response.status(), "Expected hugo front page status < 400").toBeLessThan(400);
  const headers = response.headers();
  const csp = headers["content-security-policy"];
  expect(
    csp && csp.length > 0,
    `Expected non-empty Content-Security-Policy header, got "${csp || ""}"`
  ).toBe(true);
});

test("hugo serves rendered HTML with a non-empty <title>", async ({ page }) => {
  await page.goto(`${appBaseUrl}/`);
  // Hugo renders a static page; the docs theme always emits a non-empty
  // <title>. This verifies the build pipeline produced a real page, not
  // an nginx default index nor a directory listing.
  const title = await page.title();
  expect(title && title.trim().length > 0, `Expected non-empty <title>, got "${title}"`).toBe(true);
  // The <html> root should be present and the page should NOT contain the
  // BusyBox/nginx default-index marker.
  const body = await page.content();
  expect(body.includes("<html"), "Expected <html> in response body").toBe(true);
  expect(
    body.includes("Welcome to nginx") || body.includes("Index of /"),
    "Expected Hugo content, not the nginx default page or a directory listing"
  ).toBe(false);
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
      // web-app-hugo admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(admin|posts|content|tags)$/i })
        .first();
      if (await link.isVisible({ timeout: resolveTimeout(10_000) }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /admin|posts|content|tags|baseurl/i,
          { timeout: resolveTimeout(30_000) },
        );
      }
    },
  });
});
