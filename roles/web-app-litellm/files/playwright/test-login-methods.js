const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");

const oidcIssuerUrl = normalizeBaseUrl(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"));

exports.register = function (shared) {
  test("login methods: with SSO on the admin UI hands the visitor to Keycloak and offers no password form", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    // nocheck: playwright-sso-ldap-gate -- gates on the sso login method, which an inventory can switch off while the sso service stays on
    test.skip(!shared.env.loginMethodSso, "LOGIN_METHOD_SSO_ENABLED=false");
    test.setTimeout(resolveTimeout(90_000));
    await page.context().clearCookies();

    await gotoOnion(page, `${shared.env.baseUrl}/ui`);
    await expect
      .poll(() => page.url(), {
        timeout: resolveTimeout(60_000),
        message: `the sign-in of the admin UI must be the Keycloak entry ${oidcIssuerUrl}/protocol/openid-connect/auth only`,
      })
      .toContain(`${oidcIssuerUrl}/protocol/openid-connect/auth`);
    expect(
      new URL(page.url()).host,
      "the admin UI must not keep the visitor on its own username and password form",
    ).not.toBe(new URL(shared.env.baseUrl).host);
  });

  test("login methods: /fallback/login signs the gateway administrator in while SSO is on (break-glass)", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(120_000));
    expect(shared.env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
    expect(shared.env.uiPassword, "LITELLM_UI_PASSWORD must be set").toBeTruthy();
    await page.context().clearCookies();

    await shared.signIn(page);
  });
};
