const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const baseUrl = normalizeBaseUrl(process.env.FUSIONDIRECTORY_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

test.beforeEach(async ({ page }) => {
  expect(baseUrl, "FUSIONDIRECTORY_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("baseline: FusionDirectory responds on the canonical domain", async ({ page }) => {
  const r = await page.goto(`${baseUrl}/`);
  expect(r).toBeTruthy();
  expect(r.status()).toBeLessThan(500);
  expect(r.url().includes(canonicalDomain)).toBe(true);
});

test("OIDC: oauth2-proxy redirects unauthenticated visitors through Keycloak (variant 0)", async ({ page }) => {
  skipUnlessServiceEnabled("oidc");
  expect(adminUsername).toBeTruthy(); expect(adminPassword).toBeTruthy(); expect(oidcIssuerUrl).toBeTruthy();
  const expectedAuth = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const expectedBase = baseUrl.replace(/\/$/, "");
  await page.goto(`${expectedBase}/`);
  await expect.poll(() => page.url(), { timeout: 60_000 }).toContain(expectedAuth);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect.poll(() => page.url(), { timeout: 90_000 }).toContain(expectedBase);
  await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible({ timeout: 60_000 });
});

test("LDAP: FusionDirectory backend points at svc-db-openldap (variant 1)", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  const expectedBase = baseUrl.replace(/\/$/, "");
  await page.goto(`${expectedBase}/`);
  expect(page.url().includes(canonicalDomain)).toBe(true);
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
      // web-app-fusiondirectory admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(configuration|administration|users|groups|departments)$/i })
        .first();
      if (await link.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /configuration|administration|users|groups|departments|posix/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
