const { test, expect } = require("@playwright/test");

const { gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const localLoginOffered =
  process.env.LOGIN_METHOD_NATIVE_ENABLED === "true" || process.env.LOGIN_METHOD_LDAP_ENABLED === "true";
const emailLoginOffered = process.env.LOGIN_METHOD_EMAIL_ENABLED === "true";

function baseUrl() {
  return normalizeBaseUrl(requireDotenvValue(process.env.DISCOURSE_BASE_URL, "DISCOURSE_BASE_URL"));
}

function register() {
  test("login methods: with SSO on the sign-in and sign-up pages offer only the enabled entries", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(180_000));
    const base = baseUrl();
    const keycloakAuth = `${normalizeBaseUrl(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"))}/protocol/openid-connect/auth`;
    if (localLoginOffered) {
      await gotoOnion(page, `${base}/login`);
      await expect(page.locator("#login-account-name"), "expected the local form the native or ldap method keeps").toBeEditable({
        timeout: resolveTimeout(30_000),
      });
      await expect(page.locator("#email-login-link, #one-time-code-link")).toHaveCount(emailLoginOffered ? 1 : 0);
      return;
    }
    for (const path of ["/login", "/signup"]) {
      await page.context().clearCookies();
      await gotoOnion(page, `${base}${path}`);
      await expect
        .poll(() => page.url(), {
          timeout: resolveTimeout(60_000),
          message: `expected ${path} to hand over to Keycloak at once: Discourse does so only when the OIDC button is its single sign-in entry`,
        })
        .toContain(keycloakAuth);
    }
  });

  test("login methods: the administrator break-glass form at /u/admin-login stays reachable with SSO on", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    await gotoOnion(page, `${baseUrl()}/u/admin-login`);
    await expect(page.locator("input#email"), "expected the admin-login email form that bypasses the disabled local logins").toBeEditable({
      timeout: resolveTimeout(30_000),
    });
  });
}

module.exports = { register };
