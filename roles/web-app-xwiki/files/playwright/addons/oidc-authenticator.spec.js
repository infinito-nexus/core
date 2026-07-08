const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");

const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const {
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
} = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test("oidc-authenticator: XWiki login is coupled to the Keycloak OIDC provider", async ({ page }) => {
  skipUnlessAddonEnabled("oidc-authenticator");
  skipUnlessServiceEnabled("sso");

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
  await page.goto(`${base}/bin/login/XWiki/XWikiLogin`, {
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

  // The authorization endpoint must live on the external Keycloak/IdP host,
  // not on the XWiki host itself — proving the redirect targets the
  // configured provider rather than looping back to a local login form.
  // Both hosts share the deployment's registrable parent domain (XWiki is
  // served at x.wiki.<DOMAIN_PRIMARY>, Keycloak at auth.<DOMAIN_PRIMARY>),
  // so the IdP host must differ from the XWiki host yet share that parent.
  const idpHost = new URL(authUrl).hostname;
  const parentDomain = xwikiHost.split(".").slice(-2).join(".");
  expect(
    idpHost,
    `expected the OIDC authorization endpoint to live on the external Keycloak host, not the XWiki host (${xwikiHost}); got ${idpHost}`,
  ).not.toBe(xwikiHost);
  expect(
    idpHost.endsWith(parentDomain),
    `expected the OIDC authorization endpoint host (${idpHost}) to belong to the deployment domain (${parentDomain}, derived from ${xwikiHost})`,
  ).toBe(true);

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
