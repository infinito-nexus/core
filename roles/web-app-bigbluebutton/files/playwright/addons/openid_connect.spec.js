const { test, expect } = require("@playwright/test");
const { resolveTimeout, isOnionTarget } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion, normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const bbbBaseUrl = normalizeBaseUrl(process.env.BBB_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");

test("addon openid_connect: Greenlight's external authentication resolves to Keycloak with the OAuth client", async ({ page }) => {
  skipUnlessAddonEnabled("openid_connect");
  skipUnlessServiceEnabled("sso");
  test.skip(isOnionTarget(), "BigBlueButton is WebRTC (UDP/ICE); not served over Tor");
  test.setTimeout(resolveTimeout(180_000));

  test.skip(!bbbBaseUrl || !oidcIssuerUrl, "BBB_BASE_URL / OIDC_ISSUER_URL are not staged for this role");

  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await page.context().clearCookies();
  await gotoOnion(page, `${bbbBaseUrl}/?sso=true`);

  await page
    .waitForURL((u) => u.toString().includes(expectedOidcAuthUrl), { timeout: resolveTimeout(10_000) })
    .catch(async () => {
      const oidcButton = page
        .locator("a, button")
        .filter({ hasText: /sign\s*in\s*with|openid|oidc|sso|single\s*sign[-\s]*on/i })
        .first();
      if (await oidcButton.waitFor({ state: "visible", timeout: resolveTimeout(2_000) }).then(() => true).catch(() => false)) {
        await oidcButton.click({ timeout: resolveTimeout(30_000) }).catch(() => {});
      }
    });

  await page.waitForURL((u) => u.toString().includes(expectedOidcAuthUrl), { timeout: resolveTimeout(120_000) });

  const authUrl = new URL(page.url());
  expect(
    (authUrl.searchParams.get("client_id") || "").length,
    "Keycloak authorization request from Greenlight must carry the OPENID_CONNECT_CLIENT_ID rendered into the container env",
  ).toBeGreaterThan(0);

  const redirectUri = authUrl.searchParams.get("redirect_uri") || "";
  expect(
    /\/auth\/openid_connect/i.test(redirectUri),
    `Authorization request redirect_uri must point back at Greenlight's openid_connect callback (got: ${redirectUri || "<none>"})`,
  ).toBe(true);
});
