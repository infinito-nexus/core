const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion } = require("../personas");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("addon taiga-contrib-oidc-auth: the login route resolves to the Keycloak authorization endpoint with the OAuth client", async ({ page }) => {
  skipUnlessAddonEnabled("taiga-contrib-oidc-auth");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000));

  const taigaUrls = shared.getTaigaUrls();
  test.skip(
    !taigaUrls.expectedTaigaBaseUrl || !taigaUrls.expectedOidcAuthUrl,
    "TAIGA_BASE_URL / OIDC_ISSUER_URL are not staged for this role",
  );

  await page.context().clearCookies();
  await gotoOnion(page, `${taigaUrls.expectedTaigaBaseUrl}/login`, { waitUntil: "domcontentloaded" });

  const entry = await shared.reachTopLevelTaigaAuthEntry(
    page,
    taigaUrls,
    resolveTimeout(60_000),
    "Taiga /login must expose either the taiga-contrib-oidc-auth entry point or the Keycloak login page",
  );

  if (entry.kind === "taiga-oidc-entry") {
    await Promise.all([
      page.waitForURL((url) => url.toString().includes(taigaUrls.expectedOidcAuthUrl), {
        timeout: resolveTimeout(60_000),
      }),
      entry.locator.click({ timeout: resolveTimeout(30_000) }),
    ]);
  }

  const target = page.url();
  expect(
    target,
    "Taiga's OIDC entry point must land on the Keycloak openid-connect authorization endpoint: the taiga-contrib-oidc-auth frontend directive and its mozilla-django-oidc backend are both installed",
  ).toContain(taigaUrls.expectedOidcAuthUrl);

  const authUrl = new URL(target);
  expect(
    (authUrl.searchParams.get("client_id") || "").length,
    "Keycloak authorization request from Taiga must carry the configured OAuth client_id",
  ).toBeGreaterThan(0);

  const redirectUri = authUrl.searchParams.get("redirect_uri") || "";
  expect(
    redirectUri.startsWith(taigaUrls.expectedTaigaBaseUrl),
    `Authorization request redirect_uri must point back at this Taiga instance (got: ${redirectUri || "<none>"})`,
  ).toBe(true);
});
