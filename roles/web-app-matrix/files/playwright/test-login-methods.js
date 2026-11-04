const { test, expect } = require("./onion-test");
const { resolveTimeout } = require("./timeouts");
const { apiGetOnion, gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("login methods: with SSO on Element hands its sign-in entry straight to Keycloak", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    const { ldap, native, registration } = shared.loginMethods;
    // nocheck: playwright-sso-ldap-gate -- gates on the login methods that keep Element's password form, inside the sso service gate
    test.skip(native || ldap, "an inventory override keeps the password form on Element's sign-in page");
    const { elementBaseUrl, oidcIssuerUrl } = shared.env;

    const config = await (await apiGetOnion(page.request, `${elementBaseUrl}/config.json`)).json();
    expect(config.sso_redirect_options, "Element must redirect its welcome and sign-in pages to SSO").toEqual({
      on_welcome_page: true,
      on_login_page: true,
    });
    expect(
      config.setting_defaults?.["UIFeature.registration"],
      "the Create account entry follows the registration login method",
    ).toBe(registration);

    await gotoOnion(page, `${elementBaseUrl}/#/login`, { waitUntil: "domcontentloaded" });
    await page.waitForURL((url) => url.toString().startsWith(`${oidcIssuerUrl}/protocol/openid-connect/auth`), {
      timeout: resolveTimeout(60_000),
    });
  });

  test("break-glass: with SSO on the local administrator signs in through the Synapse password API", async ({ request }) => {
    shared.skipUnlessServiceEnabled("sso");
    const { adminUsername, adminPassword } = shared.env;
    const session = await shared.loginViaApi(request, adminUsername, adminPassword);
    try {
      expect(session.user_id, "the break-glass session must belong to the local administrator").toContain(`@${adminUsername}:`);
    } finally {
      await request.post(`${shared.env.matrixBaseUrl}/_matrix/client/v3/logout`, {
        headers: session.auth,
        failOnStatusCode: false,
        timeout: resolveTimeout(30_000),
      });
    }
  });
};
