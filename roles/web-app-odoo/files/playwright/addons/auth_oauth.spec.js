const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("addon auth_oauth: the login page offers the partner Keycloak provider", async ({ page }) => {
  skipUnlessAddonEnabled("auth_oauth");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000));

  const base = shared.baseUrl();
  expect(base, "ODOO_BASE_URL must be set").toBeTruthy();
  const issuerUrl = shared.env.oidcIssuerUrl.replace(/\/$/, "");
  expect(issuerUrl, "OIDC_ISSUER_URL must be set to address the partner Keycloak realm").toBeTruthy();

  const login = await page.request.get(`${base}/web/login`, {
    failOnStatusCode: false,
    timeout: resolveTimeout(60_000),
  });
  expect(login.status(), "Odoo must serve its login page").toBeLessThan(400);

  const body = await login.text();
  expect(
    body,
    "the login page must carry an /auth_oauth/signin redirect uri; its absence means the auth_oauth module is not installed or no OAuth provider row is active, so Keycloak cannot be used to sign in",
  ).toContain("/auth_oauth/signin");
  expect(
    body,
    `the provider entry must point at the partner Keycloak authorization endpoint ${issuerUrl}/protocol/openid-connect/auth, which proves the auth.oauth.provider row tasks/05_oidc.yml writes carries this deployment's issuer and client id rather than Odoo's shipped default provider`,
  ).toContain(`${issuerUrl}/protocol/openid-connect/auth`);

  const odooHost = new URL(base).hostname;
  expect(
    new URL(issuerUrl).hostname,
    `the authorization endpoint must live on the external Keycloak host, not on the Odoo host (${odooHost})`,
  ).not.toBe(odooHost);
});
