const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const baseUrl = normalizeBaseUrl(process.env.FLOWISE_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

test.beforeEach(async ({ page }) => {
  expect(baseUrl, "FLOWISE_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("baseline: Flowise responds on the canonical domain", async ({ page }) => {
  const response = await page.goto(`${baseUrl}/`);
  expect(response, "Expected Flowise response").toBeTruthy();
  expect(response.status(), "Expected Flowise status < 500").toBeLessThan(500);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the Flowise URL`
  ).toBe(true);
});

test("OIDC: oauth2-proxy redirects unauthenticated visitors through Keycloak (variant 0)", async ({ page }) => {
  skipUnlessServiceEnabled("oidc");
  expect(adminUsername, "ADMIN_USERNAME must be set when OIDC is enabled").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set when OIDC is enabled").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set when OIDC is enabled").toBeTruthy();
  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const expectedBaseUrl = baseUrl.replace(/\/$/, "");
  await page.goto(`${expectedBaseUrl}/`);
  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`
    })
    .toContain(expectedOidcAuthUrl);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect
    .poll(() => page.url(), {
      timeout: 90_000,
      message: `expected redirect back to Flowise at ${expectedBaseUrl}`
    })
    .toContain(expectedBaseUrl);
  await expect(page.locator("body")).toBeVisible({ timeout: 60_000 });
});

test("LDAP: same oauth2-proxy gate when Keycloak federates user storage from LDAP (variant 1)", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  expect(adminUsername, "ADMIN_USERNAME must be set when LDAP is enabled").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set when LDAP is enabled").toBeTruthy();
  const expectedBaseUrl = baseUrl.replace(/\/$/, "");
  await page.goto(`${expectedBaseUrl}/`);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect
    .poll(() => page.url(), {
      timeout: 90_000,
      message: `expected redirect back to Flowise at ${expectedBaseUrl}`
    })
    .toContain(expectedBaseUrl);
  await expect(page.locator("body")).toBeVisible({ timeout: 60_000 });
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
      // web-app-flowise admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(admin|api keys|chatflows|tools|credentials|users)$/i })
        .first();
      if (await link.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /api keys|chatflows|tools|credentials|users|workspaces?/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
