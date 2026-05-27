const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm, runBiberFlow, runGuestFlow } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

const baseUrl = normalizeBaseUrl(process.env.LIBRETRANSLATE_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.beforeEach(async ({ page }) => {
  expect(baseUrl, "LIBRETRANSLATE_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("libretranslate /languages API stays reachable without auth", async ({ request }) => {
  // The /languages endpoint is part of the API surface that
  // LibreTranslate authenticates with API keys; per requirement
  // 013 it MUST stay reachable even when the UI is OIDC-gated by
  // the oauth2-proxy sidecar. The role's `services.oauth2.acl.whitelist`
  // includes /languages, /translate, /detect for exactly this reason.
  const response = await request.get(`${baseUrl}/languages`);
  expect(response.status(), "Expected libretranslate /languages status < 400 without auth").toBeLessThan(400);
  const contentType = response.headers()["content-type"] || "";
  expect(
    contentType.includes("application/json"),
    `Expected JSON content-type for /languages, got "${contentType}"`
  ).toBe(true);
});

test("administrator: oauth2-proxy gates the LibreTranslate UI through Keycloak", async ({ page }) => {
  skipUnlessServiceEnabled("oidc");
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set when OIDC is enabled").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

  // The whole `/` (UI) path is gated by oauth2-proxy; navigating to
  // it triggers a redirect chain to oauth2-proxy and then to
  // Keycloak's authorization endpoint.
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
      message: `expected redirect back to LibreTranslate at ${baseUrl}`
    })
    .toContain(canonicalDomain);

  // After OIDC the UI MUST render. LibreTranslate's frontend exposes
  // the source/target language selectors and the translate button on
  // the landing page.
  await expect(page.locator("body")).toContainText(/translate|source|target|language/i, { timeout: 60_000 });

  // Logout via oauth2-proxy's sign-out endpoint and confirm the gate
  // re-engages.
  await page.goto(`${baseUrl}/oauth2/sign_out`, { waitUntil: "commit" }).catch(() => {});
  await page.context().clearCookies();
  await page.goto(`${baseUrl}/`);
  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: "expected the UI to redirect to Keycloak again after logout"
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
