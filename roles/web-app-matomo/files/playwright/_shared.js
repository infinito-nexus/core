// Shared Matomo Playwright scaffolding: env vars, the per-test setup hook, the
// consumer-role list and the host / base-domain matchers. Every *.spec.js in
// this directory requires this module so each test file applies the same
// env-presence guard and reuses the same helpers and admin-login flow.

const { expect } = require("@playwright/test");
const { decodeDotenvQuotedValue, installCspViolationObserver, normalizeBaseUrl } = require("./personas");

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);
const matomoApiToken = decodeDotenvQuotedValue(process.env.MATOMO_API_TOKEN);
const matomoTrackingScope = (process.env.MATOMO_TRACKING_SCOPE || "sub").trim().toLowerCase();

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
const matomoTargetRoles = (() => {
  const raw = process.env.MATOMO_TARGET_ROLES_JSON || "[]";
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
})();

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

// MUST mirror sys-front-inj-matomo matomo_site_domain in root scope: one shared site per registrable domain, not per subdomain
function baseDomainOf(host) {
  return String(host || "")
    .toLowerCase()
    .replace(/^(?:.*\.)?(.+\..+)$/, "$1");
}

// Tracking-site needle for a consumer host: full subdomain in 'sub' scope (one site per subdomain), registrable base in 'root' scope (one shared site)
function siteNeedleFor(host) {
  return matomoTrackingScope === "root" ? baseDomainOf(host) : hostOf(host);
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

async function loginAsAdmin(page) {
  await page.goto(`${appBaseUrl}/index.php?module=Login`);

  const usernameField = page.locator("input#login_form_login, input[name='form_login']").first();
  const passwordField = page.locator("input#login_form_password, input[name='form_password']").first();
  const submitButton = page
    .locator("input#login_form_submit, button#login_form_submit, button[type='submit'], input[type='submit']")
    .first();

  await expect(usernameField, "Expected Matomo login form username field").toBeVisible({ timeout: 60_000 });
  await usernameField.fill(adminUsername);
  await passwordField.fill(adminPassword);
  await submitButton.click();

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: "Expected Matomo login to leave the Login module",
    })
    .not.toContain("module=Login");
}

module.exports = {
  appBaseUrl,
  oidcIssuerUrl,
  adminUsername,
  adminPassword,
  biberUsername,
  biberPassword,
  canonicalDomain,
  matomoApiToken,
  matomoTrackingScope,
  matomoCanonicalDomain,
  matomoTargetRoles,
  attachDiagnostics,
  hostOf,
  baseDomainOf,
  siteNeedleFor,
  setupMatomoPage,
  loginAsAdmin,
};
