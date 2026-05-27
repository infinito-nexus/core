const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm, runBiberFlow, runGuestFlow } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const baseUrl = normalizeBaseUrl(process.env.POSTMARKS_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.beforeEach(async ({ page }) => {
  expect(baseUrl, "POSTMARKS_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("administrator: oauth2-proxy gates the Postmarks web UI through Keycloak", async ({ page }) => {
  // Postmarks has no in-app authorisation tier beyond "logged in or
  // not"; the integrated login path is provided by a sidecar
  // oauth2-proxy in front of the entire web UI.
  // The RBAC exception is documented in README.md.
  skipUnlessServiceEnabled("oidc");
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set when OIDC is enabled").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  await page.goto(`${baseUrl}/`);

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`
    })
    .toContain(expectedOidcAuthUrl);

  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `expected redirect back to Postmarks at ${baseUrl}`
    })
    .toContain(canonicalDomain);

  // Postmarks renders a bookmarks list / nav after login. Match a
  // generous set of strings so a UI tweak in upstream does not break
  // the assertion immediately.
  await expect(page.locator("body")).toContainText(/bookmarks?|posts?|new bookmark|admin|sign\s*out|logout/i, { timeout: 60_000 });

  // Logout via oauth2-proxy and confirm the gate re-engages.
  await page.goto(`${baseUrl}/oauth2/sign_out`, { waitUntil: "commit" }).catch(() => {});
  await page.context().clearCookies();
  await page.goto(`${baseUrl}/`);
  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: "expected redirect to Keycloak again after logout"
    })
    .toContain(expectedOidcAuthUrl);
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
