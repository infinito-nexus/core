const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  keycloakAdminAddUserToGroup,
  keycloakRemoveUserFromGroupViaRest,
  normalizeBaseUrl,
  performKeycloakLoginForm,
} = require("./personas");

const keycloak = {
  baseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || ""),
  realm: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME || ""),
  username: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME || ""),
  password: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD || ""),
};

const rbacGroups = {
  administrator: decodeDotenvQuotedValue(process.env.RBAC_ADMINISTRATOR_GROUP_PATH || ""),
  user: decodeDotenvQuotedValue(process.env.RBAC_USER_GROUP_PATH || ""),
};

/**
 * Keep a Keycloak user in role groups for the duration of `body`, then take it out again.
 *
 * Args:
 *   browser: Playwright browser, used for an isolated admin REST context.
 *   username: Keycloak user name to add to the groups.
 *   groupPaths: group paths with a leading slash, e.g. RBAC_USER_GROUP_PATH.
 *   body: async callback receiving `leave(groupPath)`, which takes the user out of one group early.
 */
async function withUserInGroups(browser, username, groupPaths, body) {
  for (const groupPath of groupPaths) {
    expect(groupPath, "the RBAC group path must be rendered").toBeTruthy();
  }
  expect(keycloak.baseUrl && keycloak.realm && keycloak.username && keycloak.password, "the Keycloak admin credentials must be rendered").toBeTruthy();
  const admin = await browser.newContext({ ignoreHTTPSErrors: true });
  const joined = new Set();
  const leave = async (groupPath) => {
    await keycloakRemoveUserFromGroupViaRest(
      admin.request,
      keycloak.baseUrl,
      keycloak.realm,
      keycloak.username,
      keycloak.password,
      groupPath,
      username,
    );
    joined.delete(groupPath);
  };
  try {
    for (const groupPath of groupPaths) {
      if (
        await keycloakAdminAddUserToGroup(
          admin.request,
          keycloak.baseUrl,
          keycloak.realm,
          groupPath,
          username,
          keycloak.username,
          keycloak.password,
        )
      ) {
        joined.add(groupPath);
      }
    }
    await body(leave, admin.request);
  } finally {
    for (const groupPath of [...joined]) {
      await leave(groupPath).catch((err) => console.warn(`Cleanup removal of ${username} from ${groupPath} failed: ${err}`));
    }
    await admin.close().catch(() => {});
  }
}

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

/**
 * Args:
 *   page: Playwright page holding a SuiteCRM session.
 *   appBaseUrl: base URL of SuiteCRM without a trailing slash.
 *
 * Returns true when the legacy Administration panel renders, false when SuiteCRM refuses it
 * with "Unauthorized access to administration".
 */
async function holdsAdministration(page, appBaseUrl) {
  const response = await page.request.get(`${appBaseUrl}/legacy/index.php?module=Administration&action=index`, {
    timeout: resolveTimeout(60_000),
  });
  expect(response.status(), "the legacy Administration module must answer").toBeLessThan(500);
  const body = await response.text();
  const refused = /Unauthorized access to administration/i.test(body);
  const panel = /module=Configurator/i.test(body);
  expect(refused !== panel, "the Administration response must be either the panel or the refusal").toBe(true);
  return panel;
}

module.exports = {
  holdsAdministration,
  keycloak,
  postAssertion,
  rbacGroups,
  samlLogin,
  samlLoginTo,
  sessionStatus,
  withUserInGroups,
};
