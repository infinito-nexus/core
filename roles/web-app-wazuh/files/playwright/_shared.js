const { expect } = require("@playwright/test");
const { decodeDotenvQuotedValue, normalizeBaseUrl, gotoOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");
const keycloakAdmin = require("./personas/utils/keycloak");

const env = {
  appBaseUrl: normalizeBaseUrl(process.env.APP_BASE_URL || ""),
  keycloakBaseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || ""),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME),
  superAdminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME),
  superAdminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  keycloakAdminRealm: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_REALM),
  keycloakAdminCliClientId: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID),
  rbacGroupPathPrefix: decodeDotenvQuotedValue(process.env.RBAC_GROUP_PATH_PREFIX),
  apiHostId: decodeDotenvQuotedValue(process.env.WAZUH_API_HOST_ID),
};

/**
 * Return the Wazuh API policies the dashboard obtains for the signed-in
 * user through run_as, as raw text plus the HTTP statuses on the way.
 *
 * Args:
 *   page: a Playwright page whose context carries the dashboard session.
 */
async function wazuhApiPolicies(page) {
  const headers = { "osd-xsrf": "kibana", "Content-Type": "application/json" };
  const login = await page.request.post(`${env.appBaseUrl}/api/login`, {
    headers,
    data: { idHost: env.apiHostId, force: true },
    failOnStatusCode: false,
    timeout: resolveTimeout(60_000),
  });
  if (!login.ok()) {
    return { loginStatus: login.status(), status: 0, text: (await login.text()).slice(0, 1000) };
  }
  const response = await page.request.post(`${env.appBaseUrl}/api/request`, {
    headers,
    data: { method: "GET", path: "/security/users/me/policies", body: {}, id: env.apiHostId },
    failOnStatusCode: false,
    timeout: resolveTimeout(60_000),
  });
  return { loginStatus: login.status(), status: response.status(), text: await response.text() };
}

function attachDiagnostics(page) {
  const consoleErrors = [];
  const pageErrors = [];
  const cspRelated = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
    if (/content security policy|csp/i.test(message.text())) {
      cspRelated.push({ source: "console", text: message.text() });
    }
  });
  page.on("pageerror", (error) => {
    const text = String(error);
    pageErrors.push(text);
    if (/content security policy|csp/i.test(text)) {
      cspRelated.push({ source: "pageerror", text });
    }
  });
  return { consoleErrors, pageErrors, cspRelated };
}

async function wazuhLoginViaOidc(page, appBaseUrl, username, password) {
  await gotoOnion(page, `${appBaseUrl}/`, { waitUntil: "domcontentloaded" });

  if (!page.url().includes("openid-connect/auth")) {
    const strictLink = page
      .getByRole("link", { name: /^\s*(log\s*in|sign\s*in|login|sso)\s*$/i })
      .or(page.getByRole("button", { name: /^\s*(log\s*in|sign\s*in|login|sso)\s*$/i }))
      .first();
    const looseLink = page
      .getByRole("link", { name: /log\s*in|sign\s*in|sso/i })
      .or(page.getByRole("button", { name: /log\s*in|sign\s*in|sso/i }))
      .first();
    await keycloakAdmin.clickOidcLoginLink(page, strictLink, looseLink);
  }

  if (page.url().includes("openid-connect/auth")) {
    await keycloakAdmin.performKeycloakLoginForm(page, username, password);
  }

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `Expected redirect back to ${appBaseUrl} after OIDC login`,
    })
    .toContain(new URL(appBaseUrl).host);
  await expect
    .poll(async () => (await page.context().cookies()).length, {
      timeout: resolveTimeout(30_000),
      message:
        `Expected a real session cookie after OIDC login to ${appBaseUrl} ` +
        `(got 0 - the URL matched but no session was actually established)`,
    })
    .toBeGreaterThan(0);
}

async function withBiberInGroup(browser, groupPath, fn) {
  const adminOpts = { adminRealm: env.keycloakAdminRealm, adminClientId: env.keycloakAdminCliClientId };
  const adminCtx = await browser.newContext({ ignoreHTTPSErrors: true });
  let biberAdded = false;
  let bodyFailed = false;
  try {
    biberAdded = await keycloakAdmin.keycloakAdminAddUserToGroup(
      adminCtx.request,
      env.keycloakBaseUrl,
      env.realmName,
      groupPath,
      env.biberUsername,
      env.superAdminUsername,
      env.superAdminPassword,
      adminOpts,
    );
    return await fn();
  } catch (err) {
    bodyFailed = true;
    throw err;
  } finally {
    try {
      if (biberAdded) {
        await keycloakAdmin
          .keycloakRemoveUserFromGroupViaRest(
            adminCtx.request,
            env.keycloakBaseUrl,
            env.realmName,
            env.superAdminUsername,
            env.superAdminPassword,
            groupPath,
            env.biberUsername,
            adminOpts,
          )
          .catch((err) => {
            if (!bodyFailed) throw err;
            console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`);
          });
      }
    } finally {
      await adminCtx.close().catch(() => {});
    }
  }
}

module.exports = {
  env,
  attachDiagnostics,
  wazuhApiPolicies,
  wazuhLoginViaOidc,
  withBiberInGroup,
};
