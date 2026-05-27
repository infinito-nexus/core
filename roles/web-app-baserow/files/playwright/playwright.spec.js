const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const baseUrl = normalizeBaseUrl(process.env.BASEROW_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

test.beforeEach(async ({ page }) => {
  expect(baseUrl, "BASEROW_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("baseline: Baserow responds on the canonical domain", async ({ page }) => {
  const r = await page.goto(`${baseUrl}/`);
  expect(r, "Expected Baserow response").toBeTruthy();
  expect(r.status(), "Expected Baserow status < 500").toBeLessThan(500);
  expect(r.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the Baserow URL`).toBe(true);
});

test("OIDC: oauth2-proxy redirects unauthenticated visitors through Keycloak (variant 0)", async ({ page }) => {
  skipUnlessServiceEnabled("oidc");
  expect(adminUsername).toBeTruthy(); expect(adminPassword).toBeTruthy(); expect(oidcIssuerUrl).toBeTruthy();
  const expectedAuth = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const expectedBase = baseUrl.replace(/\/$/, "");
  await page.goto(`${expectedBase}/`);
  await expect.poll(() => page.url(), { timeout: 60_000, message: `expected redirect to ${expectedAuth}` }).toContain(expectedAuth);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect.poll(() => page.url(), { timeout: 90_000, message: `expected redirect back to ${expectedBase}` }).toContain(expectedBase);
  await expect(page.locator("body")).toBeVisible({ timeout: 60_000 });
});

test("LDAP: same oauth2-proxy gate when Keycloak federates user storage from LDAP (variant 1)", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceEnabled("oidc");
  expect(adminUsername).toBeTruthy(); expect(adminPassword).toBeTruthy();
  const expectedBase = baseUrl.replace(/\/$/, "");
  await page.goto(`${expectedBase}/`);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect.poll(() => page.url(), { timeout: 90_000, message: `expected redirect back to ${expectedBase}` }).toContain(expectedBase);
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
      // Baserow admin-only interaction: open the workspace / settings panel.
      const settingsLink = interactivePage
        .getByRole("link", { name: /^(workspaces?|settings|admin|users)$/i })
        .first();
      if (await settingsLink.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await settingsLink.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /workspace|settings|users|members|database|table/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
