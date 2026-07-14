const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.beforeEach(async ({ page }) => {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("bridgy-fed responds under canonical domain with TLS", async ({ page }) => {
  // Bridgy Fed serves a 404 on `/` by design: the canonical landing
  // surfaces are the federation-protocol endpoints (e.g. `/robots.txt`,
  // `/.well-known/host-meta`, `/web/<actor>`), not a generic homepage.
  // The deploy contract this role MUST satisfy is that the HTTP server
  // answers on the canonical domain over TLS, regardless of whether
  // the requested path resolves. A 5xx is the only signal of an
  // unhealthy app.
  const response = await gotoOnion(page, `${appBaseUrl}/`);
  expect(response, "Expected bridgy-fed response").toBeTruthy();
  expect(response.status(), "Expected bridgy-fed status < 500 (4xx are by design)").toBeLessThan(500);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the bridgy-fed URL`
  ).toBe(true);
});

test("bridgy-fed serves /robots.txt successfully", async ({ request }) => {
  // Bridgy Fed has no local user accounts and authenticates federation
  // peers via their source-platform credentials, so login / logout
  // scenarios are not applicable. The SSO and RBAC exception is
  // documented in README.md and lifecycle.md.
  // /robots.txt is the canonical "service is alive" probe for this
  // role; the homepage at `/` is a 404 by design.
  const response = await request.get(`${appBaseUrl}/robots.txt`);
  expect(response.status(), "Expected bridgy-fed /robots.txt status < 400").toBeLessThan(400);
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
      // web-app-bridgy-fed admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(admin|status|federation)$/i })
        .first();
      if (await link.isVisible({ timeout: resolveTimeout(10_000) }).catch(() => false)) {
        await link.click({ timeout: resolveTimeout(30_000) }).catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /status|federation|web|fediverse/i,
          { timeout: resolveTimeout(30_000) },
        );
      }
    },
  });
});
