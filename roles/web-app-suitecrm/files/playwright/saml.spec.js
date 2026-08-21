// @ts-check
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  assertCspInjections,
  assertUnauthenticatedLanding,
  decodeDotenvQuoted,
  gotoOnion,
  inAppLogout,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  safeIsEnabled,
} = require("./personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL);
const canonicalDomain = decodeDotenvQuoted(process.env.CANONICAL_DOMAIN);
const biberUsername = decodeDotenvQuoted(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuoted(process.env.BIBER_PASSWORD);
const adminUsername = decodeDotenvQuoted(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuoted(process.env.ADMIN_PASSWORD);

test.beforeEach(async ({ page }) => {
  test.skip(!safeIsEnabled("sso"), "SSO is disabled — SuiteCRM does not speak SAML here");
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  await page.context().clearCookies();
});

/** Drive the whole SAML round trip and return SuiteCRM's session state. */
async function samlLogin(page, username, password) {
  const landing = await gotoOnion(page, `${appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  expect(landing, "the app must answer the initial navigation").toBeTruthy();
  expect(landing.status(), "the app must not error before handing over to Keycloak").toBeLessThan(400);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message:
        "with AUTH_TYPE=saml the Symfony firewall's entry point must redirect an " +
        "unauthenticated request to Keycloak",
    })
    .toMatch(/\/protocol\/saml|\/login-actions\//);

  const assertionPosted = page.waitForResponse(
    (response) => response.url().includes("/saml/acs"),
    { timeout: resolveTimeout(120_000) },
  );
  await performKeycloakLoginForm(page, username, password);
  const acs = await assertionPosted;
  expect(
    acs.status(),
    "the assertion consumer must accept the assertion and redirect, not error",
  ).toBeLessThan(400);

  await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(60_000) }).catch(() => {});

  const response = await page.request.get(`${appBaseUrl}/session-status`, {
    timeout: resolveTimeout(30_000),
  });
  expect(response.status(), "session-status must answer").toBeLessThan(400);
  return response.json();
}

test("biber: the SAML round trip establishes a SuiteCRM session carrying the assertion's attributes", async ({ page }) => {
  const status = await samlLogin(page, biberUsername, biberPassword);

  expect(
    status.active,
    "SuiteCRM must own a session after the assertion — an edge-only login leaves active:false",
  ).toBe(true);
  expect(status.userName).toBe(biberUsername);
  expect(
    status.firstName || status.lastName,
    "SAML_AUTOCREATE_ATTRIBUTES_MAP must carry the assertion's name attributes into the record",
  ).toBeTruthy();
});

test("administrator: the SAML round trip establishes a SuiteCRM session", async ({ page }) => {
  const status = await samlLogin(page, adminUsername, adminPassword);

  expect(status.active, "SuiteCRM must own a session after the assertion").toBe(true);
  expect(status.userName).toBe(adminUsername);
});

test("biber: the authenticated surface carries the injector CSP and the in-app logout ends the session", async ({ page }) => {
  const before = await samlLogin(page, biberUsername, biberPassword);
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
