const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion } = require("../personas");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("addon social_login_key: Frappe's login offers the deployed Keycloak and hands over to it", async ({ page }) => {
  skipUnlessAddonEnabled("social_login_key");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000));

  const { erpnextBaseUrl, oidcIssuerUrl } = shared.env;
  expect(erpnextBaseUrl, "ERPNEXT_BASE_URL must be set").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set when SSO is on").toBeTruthy();

  await page.context().clearCookies();
  await gotoOnion(page, `${erpnextBaseUrl}/login`);

  const oidcSignIn = page
    .locator("a, button")
    .filter({ hasText: /sso\s*login|sign\s*in\s+with|continue\s+with|single\s+sign[-\s]*on|keycloak|infinito/i })
    .first();

  await expect(
    oidcSignIn,
    "the Social Login Key must render its provider button on /login; an absent button means the " +
      "doctype was never written or the Frappe workers did not pick it up",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });

  await oidcSignIn.click({ timeout: resolveTimeout(30_000) });

  const expectedAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message:
        `the provider button must hand over to the configured issuer (${expectedAuthUrl}); a ` +
        "different host means the Social Login Key points at another Keycloak than the deployed one",
    })
    .toContain(expectedAuthUrl);

  expect(
    new URL(page.url()).searchParams.get("client_id"),
    "the authorization request must carry the OIDC client id this deployment registered",
  ).toBeTruthy();
});
