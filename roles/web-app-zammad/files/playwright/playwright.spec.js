const { test, expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm, runGuestFlow } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

test.use({ ignoreHTTPSErrors: true });

const oidcIssuerUrl  = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const zammadBaseUrl  = normalizeBaseUrl(process.env.ZAMMAD_BASE_URL || "");
const adminUsername  = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword  = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername  = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword  = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });

  expect(zammadBaseUrl,  "ZAMMAD_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

async function zammadLogout(page) {
  await page.goto(`${zammadBaseUrl}/#logout`, { waitUntil: "commit" }).catch(() => {});
  if (oidcIssuerUrl) {
    await page.goto(`${oidcIssuerUrl}/protocol/openid-connect/logout`, { waitUntil: "commit" }).catch(() => {});
  }
  await page.context().clearCookies();
}

async function signInViaZammadOidc(page, username, password, personaLabel) {
  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await page.goto(`${zammadBaseUrl}/`);

  const oidcSignIn = page
    .locator("a, button")
    .filter({ hasText: /openid|sign\s*in\s+with|continue\s+with|single\s+sign[-\s]*on|infinito/i })
    .first();

  if ((await oidcSignIn.count().catch(() => 0)) > 0) {
    await oidcSignIn.click();
  } else {
    await page.goto(`${zammadBaseUrl}/auth/openid_connect`).catch(() => {});
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
      message: `${personaLabel}: expected redirect back to Zammad at ${zammadBaseUrl}`
    })
    .toContain(canonicalDomain);
}

test("zammad landing reachable on canonical domain", async ({ page }) => {
  const response = await page.goto(`${zammadBaseUrl}/`);
  expect(response, "Expected zammad landing response").toBeTruthy();
  expect(response.status(), "Expected zammad landing status to be < 500").toBeLessThan(500);

  const documentUrl = response.url();
  expect(
    documentUrl.includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" to back the Zammad URL`
  ).toBe(true);
});

test("administrator: zammad OIDC login lands on authenticated surface", async ({ page }) => {
  skipUnlessServiceEnabled("oidc");
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();

  await signInViaZammadOidc(page, adminUsername, adminPassword, "administrator");

  await expect(page.locator("body")).toContainText(/dashboard|ticket|overview|zammad/i, { timeout: 60_000 });

  await zammadLogout(page);
});

test("biber: zammad OIDC login lands on authenticated surface", async ({ page }) => {
  skipUnlessServiceEnabled("oidc");
  expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();

  await signInViaZammadOidc(page, biberUsername, biberPassword, "biber");

  await expect(page.locator("body")).toContainText(/dashboard|ticket|overview|zammad/i, { timeout: 60_000 });

  await zammadLogout(page);
});

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});
