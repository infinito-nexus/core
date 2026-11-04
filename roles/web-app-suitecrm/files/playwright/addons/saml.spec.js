const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion, normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");

test("addon saml: SuiteCRM hands an unauthenticated visitor to the deployed Keycloak as its SAML IdP", async ({ page }) => {
  skipUnlessAddonEnabled("saml");
  skipUnlessServiceEnabled("sso");

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();

  await page.context().clearCookies();

  const landing = await gotoOnion(page, `${appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  expect(landing, "SuiteCRM must answer the initial navigation").toBeTruthy();
  expect(
    landing.status(),
    "SuiteCRM must not error before handing the visitor over to the IdP",
  ).toBeLessThan(400);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message:
        "with this addon on, AUTH_TYPE=saml must send an unauthenticated request to Keycloak's " +
        "SAML endpoint; staying on SuiteCRM's own login form means the SAML_* contract never " +
        "reached the app and it fell back to native authentication",
    })
    .toMatch(/\/protocol\/saml|\/login-actions\//);

  const samlRequest = page.locator("input[name='SAMLRequest']");
  const idpForm = (await samlRequest.count()) > 0;
  const credentialForm = await page
    .locator("input[type='password']")
    .first()
    .isVisible()
    .catch(() => false);

  expect(
    idpForm || credentialForm,
    "the IdP must present either the signed SAMLRequest relay or its credential form; neither " +
      "means SuiteCRM reached Keycloak but not as a registered SAML service provider",
  ).toBe(true);
});
