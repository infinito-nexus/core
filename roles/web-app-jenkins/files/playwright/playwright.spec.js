const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");

const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm, runAdminFlow, runBiberFlow, runGuestFlow, gotoOnion } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const baseUrl = normalizeBaseUrl(process.env.JENKINS_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

test.beforeEach(async ({ page }) => {
  expect(baseUrl, "JENKINS_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("baseline: Jenkins responds on the canonical domain", async ({ page }) => {
  const r = await gotoOnion(page, `${baseUrl}/login`);
  expect(r).toBeTruthy();
  expect(r.status()).toBeLessThan(500);
});

test("OIDC: oic-auth plugin redirects unauthenticated visitors through Keycloak (variant 0)", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(adminUsername).toBeTruthy(); expect(adminPassword).toBeTruthy(); expect(oidcIssuerUrl).toBeTruthy();
  const expectedAuth = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const expectedBase = baseUrl.replace(/\/$/, "");
  await gotoOnion(page, `${expectedBase}/`);
  await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).toContain(expectedAuth);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect.poll(() => page.url(), { timeout: resolveTimeout(90_000) }).toContain(expectedBase);
  await expect(page.locator("body")).toBeVisible({ timeout: resolveTimeout(60_000) });
});

test("LDAP: Jenkins LDAP plugin authenticates against svc-db-openldap (variant 1)", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  const expectedBase = baseUrl.replace(/\/$/, "");
  // Jenkins LDAP login uses the local /login form rather than an
  // OIDC redirect; pin to the form path so the spec doesn't bounce
  // through Keycloak.
  await gotoOnion(page, `${expectedBase}/login`);
  const u = page.locator("input[name='j_username']").first();
  const p = page.locator("input[name='j_password']").first();
  await expect(u).toBeVisible({ timeout: resolveTimeout(60_000) });
  await u.fill(adminUsername);
  await p.fill(adminPassword);
  await page.locator("button[name='Submit'], input[type='submit']").first().click({ timeout: resolveTimeout(30_000) });
  await expect(page.locator("body")).toBeVisible({ timeout: resolveTimeout(60_000) });
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
      // web-app-jenkins admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(manage jenkins|configure system|nodes|plugins|users)$/i })
        .first();
      if (await link.isVisible({ timeout: resolveTimeout(10_000) }).catch(() => false)) {
        await link.click({ timeout: resolveTimeout(30_000) }).catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /manage jenkins|configure system|nodes|plugins|users|credentials/i,
          { timeout: resolveTimeout(30_000) },
        );
      }
    },
  });
});
