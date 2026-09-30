// Shared Matomo Playwright scaffolding: env vars, the per-test setup hook, the
// consumer-role list and the host / base-domain matchers. Every *.spec.js in
// this directory requires this module so each test file applies the same
// env-presence guard and reuses the same helpers and admin-login flow.

const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
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
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);
const domainPrimary = decodeDotenvQuotedValue(process.env.DOMAIN_PRIMARY);
const matomoApiToken = decodeDotenvQuotedValue(process.env.MATOMO_API_TOKEN);
const matomoTrackingScope = (process.env.MATOMO_TRACKING_SCOPE || "").trim().toLowerCase();

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

async function loginAsAdmin(page) {
  await gotoOnion(page, `${appBaseUrl}/index.php?module=Login`);

  const usernameField = page.locator("input#login_form_login, input[name='form_login']").first();
  const passwordField = page.locator("input#login_form_password, input[name='form_password']").first();
  const submitButton = page
    .locator("input#login_form_submit, button#login_form_submit, button[type='submit'], input[type='submit']")
    .first();

  await expect(usernameField, "Expected Matomo login form username field").toBeVisible({ timeout: resolveTimeout(60_000) });
  await usernameField.fill(adminUsername);
  await passwordField.fill(adminPassword);
  await submitButton.click();

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
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
  siteNeedleFor,
  setupMatomoPage,
  loginAsAdmin,
};
