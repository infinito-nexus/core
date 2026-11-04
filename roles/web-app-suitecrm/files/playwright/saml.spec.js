// @ts-check
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  assertCspInjections,
  assertUnauthenticatedLanding,
  decodeDotenvQuoted,
  inAppLogout,
  normalizeBaseUrl,
  safeIsEnabled,
} = require("./personas");
const { holdsAdministration, rbacGroups, samlLogin, withUserInGroups } = require("./saml-login");
const { skipUnlessServiceEnabled } = require("./service-gating");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL);
const canonicalDomain = decodeDotenvQuoted(process.env.CANONICAL_DOMAIN);
const biberUsername = decodeDotenvQuoted(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuoted(process.env.BIBER_PASSWORD);
const adminUsername = decodeDotenvQuoted(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuoted(process.env.ADMIN_PASSWORD);

test.beforeEach(async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("biber: the SAML round trip establishes a SuiteCRM session carrying the assertion's attributes", async ({ page, browser }) => {
  test.setTimeout(resolveTimeout(240_000)); // group join, SAML round trip and group removal
  await withUserInGroups(browser, biberUsername, [rbacGroups.user], async () => {
    const status = await samlLogin(page, appBaseUrl, biberUsername, biberPassword);

    expect(
      status.active,
      "SuiteCRM must own a session after the assertion — an edge-only login leaves active:false",
    ).toBe(true);
    expect(status.userName).toBe(biberUsername);
    expect(
      status.firstName || status.lastName,
      "SAML_AUTOCREATE_ATTRIBUTES_MAP must carry the assertion's name attributes into the record",
    ).toBeTruthy();
    expect(
      await holdsAdministration(page, appBaseUrl),
      "biber holds only the user group, so files/php/iam/saml_directory_sync.php must leave it without the admin flag",
    ).toBe(false);
  });
  await page.context().clearCookies();
});

test("administrator: the SAML round trip establishes a SuiteCRM session", async ({ page }) => {
  const status = await samlLogin(page, appBaseUrl, adminUsername, adminPassword);

  expect(status.active, "SuiteCRM must own a session after the assertion").toBe(true);
  expect(status.userName).toBe(adminUsername);
  expect(
    await holdsAdministration(page, appBaseUrl),
    "the platform administrator must keep the SuiteCRM admin flag",
  ).toBe(true);
  await page.context().clearCookies();
});

test("biber: the authenticated surface carries the injector CSP and the in-app logout ends the session", async ({ page, browser }) => {
  test.setTimeout(resolveTimeout(240_000)); // group join, SAML round trip, logout and group removal
  await withUserInGroups(browser, biberUsername, [rbacGroups.user], async () => {
    const before = await samlLogin(page, appBaseUrl, biberUsername, biberPassword);
    expect(before.active, "the session must exist before a logout can mean anything").toBe(true);

    await assertCspInjections(page, { isEnabled: safeIsEnabled });

    await inAppLogout(page);

    const response = await page.request.get(`${appBaseUrl}/session-status`, {
      timeout: resolveTimeout(30_000),
    });
    expect(response.status(), "session-status must answer after the logout").toBeLessThan(400);
    expect(
      (await response.json()).active,
      "the in-app logout must end SuiteCRM's own session, not merely the edge one",
    ).toBe(false);

    await assertUnauthenticatedLanding(page, appBaseUrl);
  });
});

require("./test-rbac").register();
