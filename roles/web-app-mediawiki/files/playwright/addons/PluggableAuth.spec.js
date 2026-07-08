const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");

const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

// PluggableAuth is the auth framework backing OpenIDConnect. The role wires it
// with EnableAutoLogin=true / EnableLocalLogin=false, so a wiki where the
// framework is actually loaded AND bound to the OIDC plugin must NOT serve the
// stock local username/password login form on Special:UserLogin — it must
// instead hand off to the OIDC issuer (Keycloak) or render only the
// PluggableAuth SSO affordance. This test fails if PluggableAuth is absent or
// not coupled to the IdP.
test("PluggableAuth: framework replaces local login and is bound to the OIDC issuer", async ({
  page,
}) => {
  skipUnlessAddonEnabled("PluggableAuth");
  skipUnlessServiceEnabled("sso");

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();

  await page.context().clearCookies();

  const loginUrl = `${appBaseUrl}/index.php?title=Special:UserLogin`;
  await page.goto(loginUrl, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });

  // Let an EnableAutoLogin handoff to the IdP settle.
  await page
    .waitForLoadState("networkidle", { timeout: resolveTimeout(60_000) })
    .catch(() => {});

  const finalUrl = page.url();
  const redirectedAway = !finalUrl.includes("Special:UserLogin");

  if (redirectedAway) {
    // EnableAutoLogin handed off to the configured OIDC issuer. Prove the
    // landing page is genuinely an OAuth2/OIDC authorization surface coupled to
    // this wiki, not an arbitrary redirect: the OIDC client sends the wiki's
    // redirect_uri back to itself and Keycloak renders a recognizable login.
    const url = new URL(finalUrl);
    const looksLikeAuthEndpoint =
      /\/(auth|authorize|protocol\/openid-connect\/auth|oauth2?\/authorize)/i.test(
        url.pathname,
      ) || url.searchParams.has("redirect_uri");

    expect(
      looksLikeAuthEndpoint,
      `auto-login should land on the OIDC authorization endpoint, got ${finalUrl}`,
    ).toBeTruthy();

    // The OAuth request must carry this wiki as the client redirect target,
    // proving the clientID/providerURL coupling from $wgPluggableAuth_Config.
    const redirectUri = url.searchParams.get("redirect_uri") || "";
    if (redirectUri) {
      expect(
        decodeURIComponent(redirectUri),
        "OIDC redirect_uri must point back at this wiki",
      ).toContain(canonicalDomain);
    }

    await expect(page.locator("body")).toContainText(
      /sign in|log ?in|username|password|keycloak|openid/i,
      { timeout: resolveTimeout(60_000) },
    );
    return;
  }

  // No auto-redirect: we are still on Special:UserLogin. PluggableAuth with
  // EnableLocalLogin=false must have suppressed the stock local credential form
  // and exposed only the SSO affordance bound to OIDC.
  const body = page.locator("body");

  await expect(body).toContainText(
    /single sign[- ]?on|openid|\bsso\b|log ?in with|continue with|keycloak/i,
    { timeout: resolveTimeout(60_000) },
  );

  // Stock MediaWiki local login has a password input named "wpPassword". With
  // EnableLocalLogin=false the framework removes it; its presence would mean
  // PluggableAuth is not actually driving the login surface.
  await expect(
    page.locator('input[name="wpPassword"]'),
    "local password field must be absent when PluggableAuth owns login",
  ).toHaveCount(0);
});
