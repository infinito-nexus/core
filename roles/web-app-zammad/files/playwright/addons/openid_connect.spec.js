const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("addon openid_connect: Zammad's third-party auth route hands off to the partner Keycloak", async ({ page }) => {
  skipUnlessAddonEnabled("openid_connect");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000));

  const { zammadBaseUrl, oidcIssuerUrl } = shared.env;
  expect(zammadBaseUrl, "ZAMMAD_BASE_URL must be set").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set to address the partner Keycloak realm").toBeTruthy();

  await page.context().clearCookies();

  const response = await page.request.get(`${zammadBaseUrl}/auth/openid_connect`, {
    maxRedirects: 0,
    failOnStatusCode: false,
    timeout: resolveTimeout(60_000),
  });

  expect(
    response.status(),
    `Zammad must answer /auth/openid_connect with a redirect once Setting auth_openid_connect is on; a 404 means the provider was never registered and a 200 means Zammad rendered its own form instead of handing off (HTTP ${response.status()})`,
  ).toBeGreaterThanOrEqual(300);
  expect(response.status(), "the third-party auth route must redirect, not error").toBeLessThan(400);

  const location = response.headers().location || "";
  expect(
    location,
    "the redirect must carry a Location header naming the identity provider",
  ).toBeTruthy();
  expect(
    location.startsWith(`${oidcIssuerUrl}/protocol/openid-connect/auth`),
    `the hand-off must target the partner Keycloak authorization endpoint ${oidcIssuerUrl}/protocol/openid-connect/auth, proving auth_openid_connect carries the issuer, client id and redirect uri this deployment provisioned; got ${location}`,
  ).toBe(true);

  const zammadHost = new URL(zammadBaseUrl).hostname;
  expect(
    new URL(location).hostname,
    `the authorization endpoint must live on the external Keycloak host, not on the Zammad host (${zammadHost})`,
  ).not.toBe(zammadHost);
});
