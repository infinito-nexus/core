const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

const {
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
} = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const baseUrl = normalizeBaseUrl(process.env.PENPOT_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

test.beforeEach(async ({ page }) => {
  expect(baseUrl, "PENPOT_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("baseline: Penpot responds on the canonical domain with TLS", async ({ page }) => {
  const r = await page.goto(`${baseUrl}/`);
  expect(r, "Expected Penpot response").toBeTruthy();
  expect(r.status(), "Expected Penpot front page status < 500").toBeLessThan(500);
  expect(
    r.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the Penpot URL`,
  ).toBe(true);
  expect(r.headers()["strict-transport-security"], "Penpot must emit HSTS").toBeTruthy();
});

test("OIDC: in-app provider button hands off to Keycloak and back (variant 0)", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(120_000); // OIDC round-trip + admin login form
  expect(adminUsername).toBeTruthy();
  expect(adminPassword).toBeTruthy();
  expect(oidcIssuerUrl).toBeTruthy();
  const expectedAuth = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const expectedBase = baseUrl.replace(/\/$/, "");

  // Penpot uses in-app OIDC (flavor: oidc), so the auth login page renders an
  // explicit provider button rather than auto-redirecting like an oauth2 proxy.
  await page.goto(`${expectedBase}/#/auth/login`);
  const oidcButton = page
    .getByRole("button", { name: /openid|oidc|keycloak|single sign|sso/i })
    .or(page.getByRole("link", { name: /openid|oidc|keycloak|single sign|sso/i }))
    .first();
  await expect(oidcButton, "Expected a Penpot OIDC login button").toBeVisible({ timeout: 60_000 });
  await oidcButton.click();

  await expect
    .poll(() => page.url(), { timeout: 60_000, message: `expected redirect to ${expectedAuth}` })
    .toContain(expectedAuth);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect
    .poll(() => page.url(), { timeout: 90_000, message: `expected redirect back to ${expectedBase}` })
    .toContain(expectedBase);
  await expect(page.locator("body")).toBeVisible({ timeout: 60_000 });
});

test("LDAP: in-app login form binds against OpenLDAP (variant 1)", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  test.setTimeout(90_000); // LDAP bind + first authenticated render
  expect(adminUsername).toBeTruthy();
  expect(adminPassword).toBeTruthy();
  const expectedBase = baseUrl.replace(/\/$/, "");

  // With LDAP enabled, Penpot's own login form authenticates the bind path
  // directly (no Keycloak round-trip), so fill it and assert an authenticated
  // surface (URL leaves /auth/login and the dashboard shell renders).
  await page.goto(`${expectedBase}/#/auth/login`);
  const username = page.locator("input[name='email'], input#email, input[name='username'], input[type='email']").first();
  const password = page.locator("input[name='password'], input#password, input[type='password']").first();
  await expect(username, "Expected the Penpot login form").toBeVisible({ timeout: 60_000 });
  await username.fill(adminUsername);
  await password.fill(adminPassword);
  await password.press("Enter");

  await expect
    .poll(() => page.url(), { timeout: 60_000, message: "expected to leave the login route after LDAP bind" })
    .not.toContain("/auth/login");
  await expect(page.locator("body")).toBeVisible({ timeout: 60_000 });
});

// Persona scenarios.
// Bodies live in the shared helper roles/test-e2e-playwright/files/personas
// so every role's persona flow stays consistent.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → role interaction → universal logout", async ({ page }) => {
  await runBiberFlow(page, {
    biberInteraction: async (interactivePage) => {
      // Penpot end-user interaction: open the projects/dashboard surface.
      const dashboard = interactivePage
        .getByRole("link", { name: /^(projects|drafts|dashboard|recent)$/i })
        .first();
      if (await dashboard.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await dashboard.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /project|draft|file|board|library|penpot/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});

test("administrator: app → admin interaction → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      // Penpot admin-only interaction: open the settings / management surface.
      const settingsLink = interactivePage
        .getByRole("link", { name: /^(settings|teams?|members|profile|admin)$/i })
        .first();
      if (await settingsLink.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await settingsLink.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /settings|team|member|profile|password|penpot/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
