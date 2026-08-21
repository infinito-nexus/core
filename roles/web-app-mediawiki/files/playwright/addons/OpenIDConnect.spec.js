const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");

const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const {
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  runAdminFlow,
} = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test("OpenIDConnect: wiki login hands off to the Keycloak OIDC authorize endpoint", async ({
  page,
}) => {
  skipUnlessAddonEnabled("OpenIDConnect");
  skipUnlessServiceEnabled("sso");

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();

  await page.context().clearCookies();

  // Drive MediaWiki's PluggableAuth login entry directly. With OpenIDConnect
  // loaded and its provider wired to Keycloak (oidc.php -> $wgPluggableAuth_Config
  // providerURL/clientID), PluggableAuth must redirect the browser to the
  // Keycloak OIDC authorization endpoint (.../protocol/openid-connect/auth?...).
  // A wiki where OpenIDConnect is NOT actually wired would instead stay on a
  // local MediaWiki login form and never reach the IdP authorize endpoint, so
  // this assertion fails the integration loudly.
  const oidcAuthorizeUrl = await new Promise((resolve) => {
    let settled = false;
    const done = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };

    page.on("request", (request) => {
      if (/\/protocol\/openid-connect\/auth(\?|$)/.test(request.url())) {
        done(request.url());
      }
    });

    page
      .goto(`${appBaseUrl}/index.php?title=Special:UserLogin&returnto=Main+Page`, {
        waitUntil: "domcontentloaded",
        timeout: resolveTimeout(60_000),
      })
      .then(() => page.waitForLoadState("networkidle", { timeout: resolveTimeout(30_000) }).catch(() => {}))
      .then(() => {
        if (/\/protocol\/openid-connect\/auth/.test(page.url())) {
          done(page.url());
          return;
        }
        done(null);
      })
      .catch(() => done(null));
  });

  expect(
    oidcAuthorizeUrl,
    "MediaWiki login did NOT redirect to the Keycloak OIDC authorize endpoint " +
      "(/protocol/openid-connect/auth) — OpenIDConnect is not wired to the Keycloak provider. " +
      `Current URL: ${page.url()}.`,
  ).toBeTruthy();

  // The authorize endpoint must be an absolute Keycloak URL on a DIFFERENT host
  // than the wiki itself — proves the provider URL points at the real partner
  // IdP (a separate Keycloak service), not a wiki-local stub or relative path.
  const authorizeHost = new URL(oidcAuthorizeUrl).host;
  const wikiHost = new URL(appBaseUrl).host;
  expect(
    authorizeHost && authorizeHost !== wikiHost,
    "OIDC authorize endpoint is not served from a distinct Keycloak IdP host " +
      `(wiki host ${wikiHost}, authorize URL ${oidcAuthorizeUrl}).`,
  ).toBe(true);

  // Full coupling: complete the OIDC round-trip through Keycloak and assert we
  // land on an authenticated MediaWiki surface (personal/logout tools that only
  // render once OpenIDConnect has authenticated the user).
  await page.context().clearCookies();
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      const wikiSurface = interactivePage
        .locator("#mw-content-text")
        .or(interactivePage.locator("#firstHeading"))
        .or(interactivePage.locator("#mw-panel"))
        .or(interactivePage.locator("body.mediawiki"))
        .first();
      await expect(wikiSurface).toBeVisible({ timeout: resolveTimeout(60_000) });

      const authenticatedMarker = interactivePage
        .locator("#pt-logout")
        .or(interactivePage.locator("#pt-userpage"))
        .or(interactivePage.locator("#p-personal a[href*='Logout' i]"))
        .or(interactivePage.locator("#p-personal a[href*='Special:UserLogout' i]"))
        .or(
          interactivePage.getByRole("link", {
            name: /log\s*out|sign\s*out|abmelden/i,
          }),
        )
        .first();
      await expect(authenticatedMarker).toBeVisible({ timeout: resolveTimeout(60_000) });
    },
  });
});
