// Shared Matomo Playwright scaffolding: env vars, the per-test setup hook, the
// consumer-role list and the host / base-domain matchers. Every *.spec.js in
// this directory requires this module so each test file applies the same
// env-presence guard and reuses the same helpers and admin-login flow.

const { expect, test } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  apiFetchOnion,
  decodeDotenvJsonList,
  decodeDotenvQuotedValue,
  gotoOnion,
  installCspViolationObserver,
  normalizeBaseUrl,
  requireDotenvValue,
} = require("./personas");

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"));
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const rbacAdminUsername = decodeDotenvQuotedValue(process.env.RBAC_ADMIN_USERNAME);
const rbacAdminPassword = decodeDotenvQuotedValue(process.env.RBAC_ADMIN_PASSWORD);
const matomoOidcPlugin = decodeDotenvQuotedValue(process.env.MATOMO_OIDC_PLUGIN);
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);
const domainPrimary = decodeDotenvQuotedValue(process.env.DOMAIN_PRIMARY);
const matomoApiToken = decodeDotenvQuotedValue(process.env.MATOMO_API_TOKEN);
const matomoTrackingScope = (process.env.MATOMO_TRACKING_SCOPE || "").trim().toLowerCase();
const nativeLoginEnabled = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const twoFactorEnforced = process.env.LOGIN_METHOD_2FA_ENFORCED === "true";
const BREAKGLASS_LOGIN_PATH = "/index.php?module=Login&fallback=local";
const SHOWCASE_VISITS = 20;

const matomoCanonicalDomain = (() => {
  try {
    return new URL(appBaseUrl).hostname;
  } catch {
    return "";
  }
})();

// Emitted at deploy time by templates/playwright.env.j2 via the
// roles_with_service('matomo') Ansible filter: one entry per role declared as a
// matomo consumer in its meta/services.yml.
const matomoTargetRoles = decodeDotenvJsonList(
  process.env.MATOMO_TARGET_ROLES_JSON,
  "MATOMO_TARGET_ROLES_JSON"
);

function attachDiagnostics(page) {
  const consoleErrors = [];
  const pageErrors = [];
  const cspRelated = [];

  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }

    if (/content security policy|csp/i.test(message.text())) {
      cspRelated.push({ source: "console", text: message.text() });
    }
  });

  page.on("pageerror", (error) => {
    const text = String(error);
    pageErrors.push(text);

    if (/content security policy|csp/i.test(text)) {
      cspRelated.push({ source: "pageerror", text });
    }
  });

  return { consoleErrors, pageErrors, cspRelated };
}

// alias_urls / main_url may be a full URL or a bare host; normalise both to the hostname before matching
function hostOf(value) {
  const s = String(value || "")
    .trim()
    .toLowerCase();
  if (!s) return "";
  try {
    return new URL(s.includes("://") ? s : `https://${s}`).hostname;
  } catch {
    return s.replace(/^[a-z][a-z0-9+.-]*:\/\//, "").split("/")[0];
  }
}

function siteRootDomainOf(host) {
  const name = hostOf(host);
  return name.endsWith(domainPrimary)
    ? domainPrimary
    : name.toLowerCase().replace(/^(?:.*\.)?(.+\..+)$/, "$1");
}

function siteNeedleFor(host) {
  return matomoTrackingScope === "root" ? siteRootDomainOf(host) : hostOf(host);
}

async function setupMatomoPage(page) {
  await page.setViewportSize({ width: 1440, height: 1100 });

  expect(appBaseUrl, "APP_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set in the Playwright env file").toBeTruthy();

  await page.context().clearCookies();
  await installCspViolationObserver(page);
}

/**
 * Args:
 *   page: Playwright page that ends signed in through Matomo's own form.
 *   username: the account's login.
 *   password: its password.
 */
async function signIn(page, username, password) {
  await gotoOnion(page, `${appBaseUrl}${BREAKGLASS_LOGIN_PATH}`);

  const usernameField = page.locator("input#login_form_login, input[name='form_login']").first();
  const passwordField = page.locator("input#login_form_password, input[name='form_password']").first();
  const submitButton = page
    .locator("input#login_form_submit, button#login_form_submit, button[type='submit'], input[type='submit']")
    .first();

  await expect(usernameField, "Expected Matomo login form username field").toBeVisible({ timeout: resolveTimeout(60_000) });
  await expect(usernameField).toBeEditable({ timeout: resolveTimeout(10_000) });
  await usernameField.fill(username);
  await expect(passwordField).toBeEditable({ timeout: resolveTimeout(10_000) });
  await passwordField.fill(password);
  await submitButton.click();

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "Expected Matomo login to leave the Login module",
    })
    .not.toContain("module=Login");
}

async function loginAsAdmin(page) {
  test.skip(twoFactorEnforced, "LOGIN_METHOD_2FA_ENFORCED=true sends the administrator to 2FA setup, which test-2fa-enrollment.js asserts");
  await signIn(page, adminUsername, adminPassword);
}

const LOGIN_FIELD = "input#login_form_login, input[name='form_login']";

function oidcButtonSelector() {
  return `form[action*='module=${matomoOidcPlugin}'] button[type='submit']`;
}

async function expectLoginForm(page, message) {
  const entry = nativeLoginEnabled ? LOGIN_FIELD : oidcButtonSelector();
  await expect(page.locator(entry).first(), message).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function startOidcLogin(page) {
  expect(matomoOidcPlugin, "MATOMO_OIDC_PLUGIN must be set in the Playwright env file").toBeTruthy();
  await gotoOnion(page, `${appBaseUrl}/`);
  const button = page.locator(oidcButtonSelector()).first();
  await expect(button, `Expected the ${matomoOidcPlugin} sign-in button on the Matomo login page`).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  await Promise.all([
    page.waitForURL(/\/protocol\/openid-connect\/auth/, { timeout: resolveTimeout(60_000) }),
    button.click(),
  ]);
}

async function matomoApi(request, method, params) {
  const response = await request.post(`${appBaseUrl}/index.php`, {
    form: { module: "API", method, format: "JSON", token_auth: matomoApiToken, ...params },
    ignoreHTTPSErrors: true,
    timeout: resolveTimeout(30_000),
  });
  expect(response.status(), `Matomo ${method} MUST respond < 400 (got ${response.status()})`).toBeLessThan(400);
  return response.json();
}

/**
 * Args:
 *   request: Playwright request context; records showcase visits for site 1 through the
 *            tracking API with documentation IPs once per day. A site that never received a
 *            visit gets Matomo's empty-site setup in place of its reports, which hides
 *            #secondNavBar, so every spec asserting the reporting UI seeds first.
 */
async function seedVisits(request) {
  const api = await apiFetchOnion(request, `${appBaseUrl}/index.php`, {
    method: "POST",
    form: {
      module: "API",
      method: "VisitsSummary.getVisits",
      format: "json",
      token_auth: matomoApiToken,
      idSite: "1",
      period: "day",
      date: "today",
    },
  });
  expect(api.status(), "VisitsSummary.getVisits must answer").toBe(200);
  const body = await api.json();
  if (Number(body.value) >= SHOWCASE_VISITS) return;
  for (let n = 1; n <= SHOWCASE_VISITS; n += 1) {
    const hit = await apiFetchOnion(request, `${appBaseUrl}/matomo.php`, {
      method: "POST",
      form: {
        idsite: "1",
        rec: "1",
        url: `${appBaseUrl}/showcase/page-${n % 5}`,
        action_name: `Showcase page ${n % 5}`,
        cip: `203.0.113.${n}`,
        _id: n.toString(16).padStart(16, "0"),
        token_auth: matomoApiToken,
      },
    });
    expect(hit.status(), "a showcase tracking hit must be accepted").toBeLessThan(400);
  }
}

module.exports = {
  appBaseUrl,
  oidcIssuerUrl,
  adminUsername,
  adminPassword,
  biberUsername,
  biberPassword,
  rbacAdminUsername,
  rbacAdminPassword,
  matomoOidcPlugin,
  canonicalDomain,
  matomoApiToken,
  matomoTrackingScope,
  matomoCanonicalDomain,
  matomoTargetRoles,
  nativeLoginEnabled,
  twoFactorEnforced,
  BREAKGLASS_LOGIN_PATH,
  LOGIN_FIELD,
  oidcButtonSelector,
  attachDiagnostics,
  hostOf,
  siteNeedleFor,
  setupMatomoPage,
  signIn,
  loginAsAdmin,
  expectLoginForm,
  startOidcLogin,
  matomoApi,
  seedVisits,
};
