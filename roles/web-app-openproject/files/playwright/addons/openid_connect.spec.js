const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");

test("addon openid_connect: the Enterprise OpenID provider drives OpenProject's own login", async ({ request }) => {
  skipUnlessAddonEnabled("openid_connect");
  test.setTimeout(resolveTimeout(120_000));

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set to address the partner Keycloak realm").toBeTruthy();

  const response = await request.get(`${appBaseUrl.replace(/\/$/, "")}/login`, {
    maxRedirects: 0,
    failOnStatusCode: false,
    timeout: resolveTimeout(60_000),
  });

  const location = response.headers().location || "";
  expect(
    location.startsWith(`${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`),
    `with an Enterprise OpenID provider registered, OpenProject's own /login must hand off to ${oidcIssuerUrl}/protocol/openid-connect/auth instead of rendering its native form; got ${location || `HTTP ${response.status()} without a Location header`}. While this addon stays disabled the deployment reaches Keycloak through the oauth2-proxy front door declared by services.sso, and this assertion is the proof that the in-app provider replaced it.`,
  ).toBe(true);
});
