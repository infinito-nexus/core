const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion, performKeycloakLoginForm } = require("./personas");

/**
 * Hand the unauthenticated app over to Keycloak and submit the Keycloak form.
 *
 * Args:
 *   page: Playwright page without a SuiteCRM session.
 *   appBaseUrl: base URL of SuiteCRM without a trailing slash.
 *   username: Keycloak user name.
 *   password: Keycloak password of that user.
 */
async function postAssertion(page, appBaseUrl, username, password) {
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
}

/**
 * Args:
 *   page: Playwright page whose context holds the SuiteCRM session cookie.
 *   appBaseUrl: base URL of SuiteCRM without a trailing slash.
 *
 * Returns:
 *   The JSON body of `/session-status`.
 */
async function sessionStatus(page, appBaseUrl) {
  const response = await page.request.get(`${appBaseUrl}/session-status`, {
    timeout: resolveTimeout(30_000),
  });
  expect(response.status(), "session-status must answer").toBeLessThan(400);
  return response.json();
}

/**
 * Drive the whole SAML round trip, land on the shell and return SuiteCRM's session state.
 *
 * Args:
 *   page: Playwright page without a SuiteCRM session.
 *   appBaseUrl: base URL of SuiteCRM without a trailing slash.
 *   username: Keycloak user name.
 *   password: Keycloak password of that user.
 *
 * Returns:
 *   The JSON body of `/session-status`.
 */
async function samlLogin(page, appBaseUrl, username, password) {
  const firstQuery = page.waitForResponse(
    (response) => response.url().includes("/api/graphql") && response.request().method() === "POST",
    { timeout: resolveTimeout(120_000) },
  );
  await postAssertion(page, appBaseUrl, username, password);
  await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(60_000) }).catch(() => {});
  expect(
    (await firstQuery).status(),
    "the shell's first GraphQL call must find the session the assertion consumer wrote, not answer 403 on an empty CSRF store",
  ).toBe(200);
  return sessionStatus(page, appBaseUrl);
}

/**
 * Drive the SAML round trip and open `url` instead of the shell the assertion consumer redirects to.
 *
 * Args:
 *   page: Playwright page without a SuiteCRM session.
 *   appBaseUrl: base URL of SuiteCRM without a trailing slash.
 *   username: Keycloak user name.
 *   password: Keycloak password of that user.
 *   url: page of SuiteCRM to open once the assertion was accepted.
 *
 * Returns:
 *   The JSON body of `/session-status`.
 */
async function samlLoginTo(page, appBaseUrl, username, password, url) {
  await postAssertion(page, appBaseUrl, username, password);
  await gotoOnion(page, url);
  return sessionStatus(page, appBaseUrl);
}

module.exports = { samlLogin, samlLoginTo };
