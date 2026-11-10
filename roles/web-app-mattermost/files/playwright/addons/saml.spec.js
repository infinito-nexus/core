const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion } = require("../personas");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("addon saml: the licensed SAML entry point reaches the partner Keycloak", async ({ page }) => {
  skipUnlessAddonEnabled("saml");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000));

  const baseUrl = shared.expectedMattermostBaseUrl();
  await gotoOnion(page, `${baseUrl}/login`, { waitUntil: "load", timeout: resolveTimeout(60_000) });

  const samlEntry = page.locator("a[href='/login/sso/saml']");
  await expect(
    samlEntry,
    "the SAML login entry point must render once the Enterprise licence activates this addon; without the licence the role stays on the OIDC path and this addon must remain disabled",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });

  const response = await page.request.get(`${baseUrl}/login/sso/saml`, {
    failOnStatusCode: false,
    maxRedirects: 0,
  });
  expect(
    response.headers()["location"] || "",
    "the SAML entry point must hand off to the partner Keycloak, not answer locally",
  ).toContain(new URL(shared.env.oidcIssuerUrl).host);
});
