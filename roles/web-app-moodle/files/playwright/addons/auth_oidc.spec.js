const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

test("addon auth_oidc: the login page bounces to the Keycloak authorization endpoint with the OAuth client", async ({ page }) => {
  skipUnlessAddonEnabled("auth_oidc");
  skipUnlessServiceEnabled("sso");

  const appBaseUrl = (process.env.APP_BASE_URL || "").replace(/\/$/, "");
  test.skip(!appBaseUrl, "APP_BASE_URL not set for this role");

  await page.context().clearCookies();
  await gotoOnion(page, `${appBaseUrl}/login/index.php`, { waitUntil: "domcontentloaded" }).catch(() => {});
  await page.waitForURL(/openid-connect\/auth/i, { timeout: resolveTimeout(30_000) }).catch(() => {});

  const target = page.url();
  expect(
    target,
    "Moodle /login/index.php must land on the Keycloak openid-connect authorization endpoint: auth_oidc installed under auth/oidc and alternateloginurl pointed at it",
  ).toMatch(/openid-connect\/auth/i);

  const authUrl = new URL(target);
  expect(
    (authUrl.searchParams.get("client_id") || "").length,
    "Keycloak authorization request from Moodle must carry the configured OAuth client_id",
  ).toBeGreaterThan(0);

  const redirectUri = authUrl.searchParams.get("redirect_uri") || "";
  expect(
    /auth\/oidc/i.test(redirectUri),
    `Authorization request redirect_uri must point back at the Moodle auth_oidc callback (got: ${redirectUri || "<none>"})`,
  ).toBe(true);
});
