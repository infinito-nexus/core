const { test, expect } = require("./onion-test");
const { resolveTimeout } = require("./timeouts");

const { apiGetOnion, gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

test.use({ ignoreHTTPSErrors: true });

function enabled(raw, name) {
  return requireDotenvValue(raw, name) === "true";
}

test("login methods: with sso on, Keycloak is OpenCloud's only identity provider", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  const base = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
  const issuer = normalizeBaseUrl(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"));

  const discovery = await apiGetOnion(page.request, `${base}/.well-known/openid-configuration`, {
    timeout: resolveTimeout(60_000),
  });
  expect(discovery.status(), "OpenCloud MUST publish the discovery document of its identity provider").toBe(200);
  expect(
    normalizeBaseUrl((await discovery.json()).issuer),
    "the identity provider OpenCloud hands its sign-in to MUST be the Keycloak realm",
  ).toBe(issuer);

  const builtinIdp =
    enabled(process.env.LOGIN_METHOD_NATIVE_ENABLED, "LOGIN_METHOD_NATIVE_ENABLED") ||
    enabled(process.env.LOGIN_METHOD_LDAP_ENABLED, "LOGIN_METHOD_LDAP_ENABLED");
  // nocheck: playwright-sso-ldap-gate -- gates on the login methods that keep the built-in identity provider, inside the sso service gate
  test.skip(builtinIdp, "an inventory override keeps the built-in identity provider running");
  await gotoOnion(page, `${base}/signin/v1/identifier`, { waitUntil: "domcontentloaded" });
  await expect(
    page.locator("#oc-login-username"),
    "with native and ldap off the built-in identity provider MUST NOT serve its sign-in form",
  ).toHaveCount(0);
});
