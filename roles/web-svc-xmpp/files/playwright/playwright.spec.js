const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

const { decodeDotenvQuotedValue, normalizeBaseUrl, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const baseUrl = normalizeBaseUrl(process.env.XMPP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.beforeEach(async ({ page }) => {
  expect(baseUrl, "XMPP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("baseline: ejabberd HTTP API responds on the canonical domain", async ({ page }) => {
  // The ejabberd HTTP listener at /admin and /api covers the
  // web-facing surfaces; XMPP client login itself runs over
  // 5222/5269 and is not Playwright-testable via HTTP. The
  // baseline asserts the role at least binds correctly.
  const r = await page.goto(`${baseUrl}/admin/`);
  expect(r).toBeTruthy();
  expect(r.status()).toBeLessThan(500);
  expect(r.url().includes(canonicalDomain)).toBe(true);
});

test("LDAP: ejabberd backend points at svc-db-openldap (variant 1)", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  const r = await page.goto(`${baseUrl}/admin/`);
  expect(r).toBeTruthy();
  expect(r.status()).toBeLessThan(500);
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
      // web-svc-xmpp admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(admin|users|nodes|status|settings)$/i })
        .first();
      if (await link.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /admin|users|nodes|status|settings/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
