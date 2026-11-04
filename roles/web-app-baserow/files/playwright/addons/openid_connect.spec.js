const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion, normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const baserowBaseUrl = normalizeBaseUrl(process.env.BASEROW_BASE_URL || "");

test("addon openid_connect: the enterprise OIDC auth provider is registered and offered on the login page", async ({ page }) => {
  skipUnlessAddonEnabled("openid_connect");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000));

  test.skip(!baserowBaseUrl, "BASEROW_BASE_URL is not staged for this role");

  await page.context().clearCookies();
  const response = await gotoOnion(page, `${baserowBaseUrl}/api/sso/oauth2/providers/`, { waitUntil: "domcontentloaded" });

  expect(
    response && response.status(),
    "Baserow's enterprise SSO provider endpoint must answer once the openid_connect auth provider is licensed and registered; it 404s while the enterprise plugin runs unlicensed",
  ).toBeLessThan(400);

  await gotoOnion(page, `${baserowBaseUrl}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});

  const providerAffordance = page
    .locator("a, button")
    .filter({ hasText: /openid|oidc|keycloak|single\s*sign[-\s]*on|sso/i })
    .first();

  await expect(
    providerAffordance,
    "Baserow's login page must offer the registered openid_connect provider; its absence means the enterprise auth provider never registered",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
});
