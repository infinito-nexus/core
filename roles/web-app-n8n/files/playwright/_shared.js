const { expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm, runGuestFlow } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");

const oidcEnabled     = isServiceEnabled("sso");
const ldapEnabled     = isServiceEnabled("ldap");
const oidcIssuerUrl   = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const n8nBaseUrl      = normalizeBaseUrl(process.env.N8N_BASE_URL || "");
const adminUsername   = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword   = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername   = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword   = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

async function n8nLogout(page) {
  if (oidcEnabled && oidcIssuerUrl) {
    await page.goto(`${n8nBaseUrl}/oauth2/sign_out`, { waitUntil: "commit" }).catch(() => {});
    await page.goto(`${oidcIssuerUrl}/protocol/openid-connect/logout`, { waitUntil: "commit" }).catch(() => {});
  } else {
    await page.goto(`${n8nBaseUrl}/signout`, { waitUntil: "commit" }).catch(() => {});
  }
  await page.context().clearCookies();
}

async function signInViaN8nOidc(page, username, password, personaLabel) {
  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await page.goto(`${n8nBaseUrl}/`);

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `${personaLabel}: expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`
    })
    .toContain(expectedOidcAuthUrl);

  await performKeycloakLoginForm(page, username, password);

  await expect
    .poll(() => page.url(), {
      timeout: 90_000,
      message: `${personaLabel}: expected redirect back to n8n at ${n8nBaseUrl}`
    })
    .toContain(canonicalDomain);
}

async function signInViaN8nLdap(page, username, password) {
  await page.context().clearCookies();
  await page.goto(`${n8nBaseUrl}/signin`, { waitUntil: "domcontentloaded" });

  const emailInput    = page.locator('input[type="email"], input[name="email"]').first();
  const passwordInput = page.locator('input[type="password"], input[name="password"]').first();
  await emailInput.waitFor({ state: "visible", timeout: 60_000 });

  await emailInput.fill(username);
  await passwordInput.fill(password);
  await page.locator('button[type="submit"]').first().click();

  await expect(emailInput).toBeHidden({ timeout: 60_000 });
  await expect
    .poll(() => page.url(), { timeout: 60_000 })
    .not.toMatch(/\/signin/);
}

async function beforeEach({ page }) {
  await page.setViewportSize({ width: 1440, height: 1100 });

  expect(n8nBaseUrl,      "N8N_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
}

module.exports = {
  env: {
    oidcEnabled,
    ldapEnabled,
    oidcIssuerUrl,
    n8nBaseUrl,
    adminUsername,
    adminPassword,
    biberUsername,
    biberPassword,
    canonicalDomain,
  },
  signInViaN8nOidc,
  signInViaN8nLdap,
  n8nLogout,
  beforeEach,
  skipUnlessServiceEnabled,
  runGuestFlow,
};
