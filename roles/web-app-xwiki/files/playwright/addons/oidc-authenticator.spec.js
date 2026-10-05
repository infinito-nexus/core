const { test, expect } = require("@playwright/test");
const { resolveTimeout, isSplitRealmOidc } = require("../timeouts");

const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  requireDotenvValue,
} = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const issuerUrl = requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL");

test("oidc-authenticator: XWiki login is coupled to the Keycloak OIDC provider", async ({ page }) => {
  skipUnlessAddonEnabled("oidc-authenticator");
  skipUnlessServiceEnabled("sso");
  test.skip(isSplitRealmOidc(), "clearnet app with an onion OIDC issuer: unreachable from one browser");

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();

  await page.context().clearCookies();

  const base = appBaseUrl.replace(/\/$/, "");
  const xwikiHost = new URL(base).hostname;

  // With the OIDC authenticator wired (authservice=oidc, oidc.provider /
  // oidc.endpoint.authorization / oidc.clientid set in xwiki.properties and
  // oidc.skipped=false), hitting the XWiki `login` action makes the
  // OIDCAuthServiceImpl redirect the browser straight to the configured
  // Keycloak authorization endpoint — no intermediate button click. If the
  // extension/config were NOT wired, the login action would instead render
  // XWiki's local username/password form on the XWiki host and never reach
  // the provider, so the assertions below would fail.
  await gotoOnion(page, `${base}/bin/login/XWiki/XWikiLogin`, {
    waitUntil: "domcontentloaded",
    timeout: resolveTimeout(60_000),
  });

  // Follow the OIDC hand-off to Keycloak's authorization endpoint. The
  // redirect is automatic for a preconfigured provider; the explicit wait
  // tolerates a slow IdP round-trip.
  await page
    .waitForURL(/\/protocol\/openid-connect\/auth/, { timeout: resolveTimeout(45_000) })
    .catch(() => {});
  await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});

  const authUrl = page.url();
  expect(
    /\/realms\/[^/]+\/protocol\/openid-connect\/auth/.test(authUrl),
    `expected the XWiki login action to hand off to the Keycloak OIDC authorization endpoint (proves oidc.provider/endpoint.authorization/clientid are wired and authservice=oidc is active), got ${authUrl}`,
  ).toBe(true);

  const idpHost = new URL(authUrl).hostname;
  expect(
    idpHost,
    `expected the OIDC authorization endpoint to live on the external Keycloak host, not the XWiki host (${xwikiHost}); got ${idpHost}`,
  ).not.toBe(xwikiHost);
  expect(
    idpHost,
    `expected the OIDC authorization endpoint host to be the one OIDC_ISSUER_URL declares (${new URL(issuerUrl).hostname}); got ${idpHost}`,
  ).toBe(new URL(issuerUrl).hostname);

  // The Keycloak login form (not an error page) must render for the
  // registered client, confirming the client_id/redirect_uri coupling.
  const keycloakLoginForm = page
    .getByRole("textbox", { name: /username|email/i })
    .or(page.locator("input[name='username'], input#username"))
    .first();

  await expect(
    keycloakLoginForm,
    "the Keycloak login form must render for the registered XWiki client, confirming the OIDC client coupling",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
});
