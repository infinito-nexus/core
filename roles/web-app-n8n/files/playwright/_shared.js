const { expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm, runGuestFlow } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");

const oidcEnabled      = isServiceEnabled("sso");
const oidcIssuerUrl    = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const n8nBaseUrl       = normalizeBaseUrl(process.env.N8N_BASE_URL || "");
const adminEmail       = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL);
const adminUsername    = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword    = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const n8nOwnerPassword = decodeDotenvQuotedValue(process.env.N8N_OWNER_PASSWORD);
const biberUsername    = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberEmail       = decodeDotenvQuotedValue(process.env.BIBER_EMAIL);
const biberPassword    = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const canonicalDomain  = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

async function n8nLogout(page) {
  if (oidcEnabled && oidcIssuerUrl) {
    await page.goto(`${n8nBaseUrl}/oauth2/sign_out`, { waitUntil: "commit" }).catch(() => {});
    await page.goto(`${oidcIssuerUrl}/protocol/openid-connect/logout`, { waitUntil: "commit" }).catch(() => {});
  } else {
    await page.goto(`${n8nBaseUrl}/signout`, { waitUntil: "commit" }).catch(() => {});
  }
  await page.context().clearCookies();
}

// Drives the Keycloak SSO round-trip through oauth2-proxy. hooks.js
// (EXTERNAL_HOOK_FILES, roles/web-app-n8n/files/hooks.js) reads the trusted
// Remote-Email header openresty sets once the oauth2-proxy auth_request gate
// passes and auto-provisions/issues n8n's own session cookie, so the redirect
// back lands directly on n8n's authenticated workflow surface — no second,
// n8n-local sign-in step. `performN8nLoginForm` (see below) is only needed
// for the V2 (no SSO) native-login path.
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

// Completes n8n's own local login form. Used by the administrator persona
// for the V2 (no SSO) journey, where the owner account (administrator's
// email + the break-glass N8N_OWNER_PASSWORD) provisioned by
// tasks/02_bootstrap.yml is the only way to reach n8n's authenticated
// surface.
async function performN8nLoginForm(page, email, password) {
  const emailInput    = page.locator('input[type="email"], input[name="email"]').first();
  const passwordInput = page.locator('input[type="password"], input[name="password"]').first();
  await emailInput.waitFor({ state: "visible", timeout: 60_000 });

  await emailInput.fill(email);
  await passwordInput.fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();

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
    oidcIssuerUrl,
    n8nBaseUrl,
    adminEmail,
    adminUsername,
    adminPassword,
    n8nOwnerPassword,
    biberUsername,
    biberEmail,
    biberPassword,
    canonicalDomain,
  },
  signInViaN8nOidc,
  performN8nLoginForm,
  n8nLogout,
  beforeEach,
  skipUnlessServiceEnabled,
  runGuestFlow,
};
