const { test, expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm, runGuestFlow } = require("./personas");
const { isServiceEnabled } = require("./service-gating");
require("./test-seaweedfs");
test.use({ ignoreHTTPSErrors: true });

const oidcEnabled = isServiceEnabled("sso");

async function peertubeLogout(page, peertubeBaseUrl) {
  await page
    .goto(`${peertubeBaseUrl}/logout`, { waitUntil: "commit" })
    .catch(() => {});
  await page.context().clearCookies();
}

const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const oidcButtonText = decodeDotenvQuotedValue(process.env.OIDC_BUTTON_TEXT || "");
const peertubeBaseUrl = normalizeBaseUrl(process.env.PEERTUBE_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });

  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(peertubeBaseUrl, "PEERTUBE_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();

  await page.context().clearCookies();
});

test("peertube landing exposes canonical domain from applications lookup", async ({ page }) => {
  const response = await page.goto(`${peertubeBaseUrl}/`);
  expect(response, "Expected peertube landing response").toBeTruthy();
  expect(response.status(), "Expected peertube landing response to be successful").toBeLessThan(400);
  expect(
    response.url().includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" (from applications lookup) to back the peertube URL`
  ).toBe(true);
});

async function signInViaDashboardOidc(page, username, password, personaLabel) {
  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await page.goto(`${peertubeBaseUrl}/login`);

  const oidcButtonPatterns = [
    oidcButtonText ? new RegExp(oidcButtonText.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i") : null,
    /open\s*id\s*connect/i,
    /single\s+sign[-\s]*on/i,
    /continue\s+with\s+oidc/i,
    /sign\s*in\s+with\s+oidc/i
  ].filter(Boolean);

  const oidcSignIn = page
    .locator("a, button")
    .filter({ hasText: oidcButtonPatterns[0] })
    .first();

  if ((await oidcSignIn.count().catch(() => 0)) > 0) {
    await oidcSignIn.click();
  } else {
    for (const pattern of oidcButtonPatterns.slice(1)) {
      const candidate = page.locator("a, button").filter({ hasText: pattern }).first();
      if ((await candidate.count().catch(() => 0)) > 0) {
        await candidate.click();
        break;
      }
    }
  }

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `${personaLabel}: expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`
    })
    .toContain(expectedOidcAuthUrl);

  await performKeycloakLoginForm(page, username, password);

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `${personaLabel}: expected redirect back to peertube at ${peertubeBaseUrl}`
    })
    .toContain(peertubeBaseUrl);

  const authenticatedMarker = page
    .locator(
      "my-avatar-menu, my-user-notifications, my-header my-avatar, a[href='/my-account'], button.dropdown-toggle my-avatar"
    )
    .first();

  await expect
    .poll(
      async () => {
        if (await authenticatedMarker.isVisible().catch(() => false)) return "marker";
        const url = page.url();
        if (url.includes("/login") || url.includes("/protocol/openid-connect/auth")) return "login";
        return "pending";
      },
      {
        timeout: 60_000,
        message: `${personaLabel}: expected visible authenticated peertube UI marker after OIDC login`
      }
    )
    .toBe("marker");
}

test("administrator: peertube OIDC login and logout", async ({ page }) => {
  test.skip(!oidcEnabled, "OIDC shared service disabled");
  await signInViaDashboardOidc(page, adminUsername, adminPassword, "administrator");

  await peertubeLogout(page, peertubeBaseUrl);

  await page.goto(`${peertubeBaseUrl}/login`);
  await expect
    .poll(
      async () =>
        (await page
          .locator("input[name='username'], input#username, a, button")
          .filter({ hasText: /login|sign\s*in|anmelden/i })
          .first()
          .count()
          .catch(() => 0)) > 0 ||
        (await page.locator("input[type='password']").count().catch(() => 0)) > 0,
      {
        timeout: 60_000,
        message: "Expected peertube to require a new sign-in after logout"
      }
    )
    .toBe(true);
});

test("biber: peertube OIDC login and logout", async ({ page }) => {
  test.skip(!oidcEnabled, "OIDC shared service disabled");
  await signInViaDashboardOidc(page, biberUsername, biberPassword, "biber");

  await peertubeLogout(page, peertubeBaseUrl);

  await page.goto(`${peertubeBaseUrl}/login`);
  await expect
    .poll(
      async () =>
        (await page
          .locator("input[name='username'], input#username, a, button")
          .filter({ hasText: /login|sign\s*in|anmelden/i })
          .first()
          .count()
          .catch(() => 0)) > 0 ||
        (await page.locator("input[type='password']").count().catch(() => 0)) > 0,
      {
        timeout: 60_000,
        message: "Expected peertube to require a new sign-in after logout"
      }
    )
    .toBe(true);
});


// Persona scenarios.
// Bodies live in the shared persona helpers under
// roles/test-e2e-playwright/files/personas/{guest,biber,admin}.js.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});
