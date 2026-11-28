const { test, expect } = require("@playwright/test");

const { gotoOnion, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { isSplitRealmOidc, resolveTimeout } = require("./timeouts");
const { webmailBaseUrl, expectedOidcAuthUrl } = require("./env");

test("login methods: with sso on, the webmail hands the sign-in to Keycloak and shows no password form", async ({ page }) => {
  test.skip(isSplitRealmOidc(), "clearnet app with an onion OIDC issuer: unreachable from one browser");
  skipUnlessServiceEnabled("sso");
  test.skip(
    requireDotenvValue(process.env.LOGIN_METHOD_NATIVE_ENABLED, "LOGIN_METHOD_NATIVE_ENABLED") === "true",
    "the inventory keeps the native Roundcube form next to the SSO entry",
  );
  await page.context().clearCookies();

  await gotoOnion(page, `${webmailBaseUrl}/`);
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "oauth_login_redirect MUST send the Roundcube sign-in straight to Keycloak",
    })
    .toContain(expectedOidcAuthUrl);
  await expect(page.locator("#rcmloginpwd"), "no Roundcube password form may sit on the SSO path").toHaveCount(0);
});
