const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { gotoOnion, normalizeBaseUrl, performKeycloakLoginForm, requireDotenvValue } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test("biber: app → keycloak → oauth2 gate refuses biber outside the postmarks administrator group", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000));
  const baseUrl = normalizeBaseUrl(requireDotenvValue(process.env.POSTMARKS_BASE_URL, "POSTMARKS_BASE_URL"));
  const oidcIssuerUrl = normalizeBaseUrl(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"));
  const biberUsername = requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME");
  const biberPassword = requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD");

  await page.context().clearCookies();
  const [callback] = await Promise.all([
    page.waitForResponse((response) => new URL(response.url()).pathname === "/oauth2/callback", {
      timeout: resolveTimeout(120_000),
    }),
    (async () => {
      await gotoOnion(page, `${baseUrl}/`);
      await expect
        .poll(() => page.url(), {
          timeout: resolveTimeout(60_000),
          message: "Expected the oauth2-proxy gate to send an anonymous visitor to Keycloak",
        })
        .toContain(`${oidcIssuerUrl}/protocol/openid-connect/auth`);
      await performKeycloakLoginForm(page, biberUsername, biberPassword);
    })(),
  ]);

  expect(
    callback.status(),
    "oauth2-proxy MUST refuse biber at /oauth2/callback: sso.oauth2.allowed_groups admits only the postmarks administrator role group",
  ).toBe(403);
  expect(
    new URL(page.url()).pathname,
    `Expected biber to stay on the oauth2-proxy refusal, never on a Postmarks page (at ${page.url()})`,
  ).toBe("/oauth2/callback");
  const cookies = await page.context().cookies(baseUrl);
  expect(
    cookies.some((cookie) => cookie.name === "connect.sid"),
    "a user outside the postmarks administrator role group MUST NOT receive a Postmarks session",
  ).toBe(false);
});
