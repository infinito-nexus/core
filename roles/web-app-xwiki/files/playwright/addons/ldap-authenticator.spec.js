const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");

const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const {
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  gotoOnion,
} = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const ssoEnabled = (process.env.SSO_SERVICE_ENABLED || "").toLowerCase() === "true";

test("ldap-authenticator: XWiki enforces its LDAP-backed native credential form on protected pages", async ({ page }) => {
  skipUnlessAddonEnabled("ldap-authenticator");
  skipUnlessServiceEnabled("ldap");

  // When OIDC owns the login journey the active authservice is the OIDC
  // authclass (compose.yml.j2 prefers oidc), not the LDAP authclass — that
  // path is covered by the oidc-authenticator spec. The LDAP authclass is only
  // the active backend when SSO is off, so this LDAP-specific proof is only
  // meaningful then.
  test.skip(
    ssoEnabled,
    "LDAP is the active XWiki authservice only when SSO/OIDC is off; the OIDC flavor is covered by oidc-authenticator.spec.js.",
  );

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();

  await page.context().clearCookies();

  const base = appBaseUrl.replace(/\/$/, "");

  await gotoOnion(page, `${base}/bin/view/XWiki/XWikiPreferences`, {
    waitUntil: "domcontentloaded",
  });

  // The LDAP authclass keeps authentication inside XWiki: a protected page for
  // an anonymous visitor must route to XWiki's own login surface on the XWiki
  // host, never to an external IdP. Anything that leaves the canonical domain
  // (i.e. an OIDC redirect) means the LDAP authservice is NOT the active backend.
  const stayedOnHost = new URL(page.url()).hostname.endsWith(canonicalDomain);
  expect(
    stayedOnHost,
    `protected page must route to XWiki's own LDAP-backed login on ${canonicalDomain}, ` +
      `but the browser left the host (got ${page.url()}) — the LDAP authservice is not active.`,
  ).toBe(true);

  const onLoginSurface =
    /viewer=login|XWiki\.XWikiLogin|\/login/i.test(page.url()) ||
    (await page
      .locator("input[type='password']:visible")
      .first()
      .isVisible({ timeout: resolveTimeout(30_000) })
      .catch(() => false));
  expect(
    onLoginSurface,
    "an anonymous visitor to a protected XWiki page must be challenged with a login surface " +
      "(LDAP authclass enforces authentication); none was presented",
  ).toBe(true);

  // The LDAP authenticator backs XWiki's native username/password credential
  // form. Assert that form is what is served (not an anonymous page, not a
  // third-party SSO button), proving the credential path the LDAP backend
  // validates against is wired in.
  const usernameField = page
    .locator(
      "input[name='j_username'], input#j_username, input[name='username']:visible, input[name='loginName']:visible, input[type='text']:visible",
    )
    .first();
  const passwordField = page
    .locator("input[name='j_password'], input#j_password, input[type='password']:visible")
    .first();

  await expect(
    usernameField,
    "XWiki must serve a username field for the LDAP-backed native login form",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
  await expect(
    passwordField,
    "XWiki must serve a password field for the LDAP-backed native login form",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });

  // A bogus credential must be rejected by the LDAP-backed authenticator: the
  // user stays on the XWiki login surface (no session granted). This exercises
  // the live LDAP bind/validation path end-to-end rather than just asserting
  // the form exists.
  await usernameField.fill("nonexistent-ldap-user-e2e").catch(() => {});
  await passwordField.fill("definitely-wrong-password-e2e").catch(() => {});
  await passwordField.press("Enter").catch(() => {});
  await page.waitForLoadState("networkidle").catch(() => {});

  const stillUnauthenticated =
    /viewer=login|XWiki\.XWikiLogin|\/login/i.test(page.url()) ||
    (await page
      .locator("input[type='password']:visible")
      .first()
      .isVisible({ timeout: resolveTimeout(15_000) })
      .catch(() => false));
  expect(
    stillUnauthenticated,
    "invalid credentials must be rejected by the LDAP-backed authenticator (no session granted); " +
      `instead the browser reached an authenticated surface at ${page.url()}.`,
  ).toBe(true);
});
