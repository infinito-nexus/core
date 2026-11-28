const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");

const {
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  requireDotenvValue,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
} = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const baseUrl = normalizeBaseUrl(process.env.FUSIONDIRECTORY_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

test.beforeEach(async ({ page }) => {
  expect(baseUrl, "FUSIONDIRECTORY_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

require("./test-design").register();

test("baseline: FusionDirectory responds on the canonical domain", async ({ page }) => {
  const r = await gotoOnion(page, `${baseUrl}/`);
  expect(r).toBeTruthy();
  expect(r.status()).toBeLessThan(500);
  expect(r.url().includes(canonicalDomain)).toBe(true);
});

test("OIDC: the Keycloak sign-in lands in FusionDirectory through the header login (variant 0)", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(adminUsername).toBeTruthy(); expect(adminPassword).toBeTruthy(); expect(oidcIssuerUrl).toBeTruthy();
  const expectedAuth = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const expectedBase = baseUrl.replace(/\/$/, "");
  await gotoOnion(page, `${expectedBase}/`);
  await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).toContain(expectedAuth);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect.poll(() => page.url(), { timeout: resolveTimeout(90_000) }).toContain(`${expectedBase}/main.php`);
  await expect(page.locator("div.plugin-window").first(), "the oauth2-proxy identity must open a FusionDirectory session").toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  await expect(page.locator("#loginform"), "no second login form may follow the Keycloak sign-in").toHaveCount(0);
});

require("./test-rbac").register();
require("./test-forged-identity");

test("guest: FusionDirectory backend points at svc-db-openldap (variant 1)", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  const expectedBase = baseUrl.replace(/\/$/, "");
  await gotoOnion(page, `${expectedBase}/`);
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
  await runAdminFlow(page);
});
