const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl, gotoOnion } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const peertubeBaseUrl = normalizeBaseUrl(process.env.PEERTUBE_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const oidcButtonText = decodeDotenvQuotedValue(process.env.OIDC_BUTTON_TEXT || "");

test("addon peertube-plugin-auth-openid-connect: the login page offers the external auth and it resolves to Keycloak with the OAuth client", async ({ page }) => {
  skipUnlessAddonEnabled("peertube-plugin-auth-openid-connect");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000));

  test.skip(!peertubeBaseUrl || !oidcIssuerUrl, "PEERTUBE_BASE_URL / OIDC_ISSUER_URL are not staged for this role");

  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const buttonPatterns = [
    oidcButtonText ? new RegExp(oidcButtonText.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i") : null,
    /open\s*id\s*connect/i,
    /single\s+sign[-\s]*on/i,
    /sign\s*in\s+with\s+oidc/i,
  ].filter(Boolean);

  await page.context().clearCookies();
  await gotoOnion(page, `${peertubeBaseUrl}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});

  await expect
    .poll(
      async () => {
        if (page.url().includes(expectedOidcAuthUrl)) return page.url();
        for (const pattern of buttonPatterns) {
          const candidate = page.locator("a, button").filter({ hasText: pattern }).first();
          if ((await candidate.count().catch(() => 0)) > 0) {
            await candidate.waitFor({ state: "visible", timeout: resolveTimeout(30_000) }).catch(() => {});
            await candidate.click().catch(() => {});
            break;
          }
        }
        return page.url();
      },
      {
        timeout: resolveTimeout(60_000),
        message: `No external-auth affordance on ${peertubeBaseUrl}/login and no redirect to ${expectedOidcAuthUrl}; PeerTube has not registered the auth-openid-connect plugin`,
      },
    )
    .toContain(expectedOidcAuthUrl);

  const authUrl = new URL(page.url());
  expect(
    (authUrl.searchParams.get("client_id") || "").length,
    "Keycloak authorization request from PeerTube must carry the client_id the plugin settings row holds",
  ).toBeGreaterThan(0);

  const redirectUri = authUrl.searchParams.get("redirect_uri") || "";
  expect(
    redirectUri.startsWith(peertubeBaseUrl),
    `Authorization request redirect_uri must point back at this PeerTube instance (got: ${redirectUri || "<none>"})`,
  ).toBe(true);
});
