const { expect } = require("@playwright/test");
const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("./personas");
// Keycloak Admin REST helpers (token fetch, group resolution, group
// membership add/remove) live in the shared persona utils so other roles
// can reuse them instead of reimplementing this logic; see
// roles/test-e2e-playwright/files/personas/utils/keycloak.js.
const keycloakAdmin = require("./personas/utils/keycloak");

const env = {
  appBaseUrl: normalizeBaseUrl(process.env.APP_BASE_URL || ""),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN),
  keycloakBaseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || ""),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME),
  oidcIssuerUrl: decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL),
  superAdminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME),
  superAdminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  // Keycloak's own built-in bootstrap realm/client for password-grant admin
  // authentication (OIDC.ADMIN.* in group_vars/all/11_oidc.yml) - distinct
  // from KEYCLOAK_REALM_NAME/OIDC_ISSUER_URL above, which are this app's
  // own OIDC client realm.
  keycloakAdminRealm: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_REALM),
  keycloakAdminCliClientId: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID),
  // Keycloak group path is `/roles/web-app-wazuh/<role>` (leading slash —
  // matches the raw `groups` claim shape documented in
  // roles/web-app-joomla/meta/rbac.yml's worked example). The spec appends
  // the role segment.
  rbacGroupPathPrefix: decodeDotenvQuotedValue(process.env.RBAC_GROUP_PATH_PREFIX),
};

// Same shape as roles/web-app-openwebui/files/playwright/_shared.js and
// roles/web-app-wordpress/files/playwright/_shared.js: page.on listeners
// persist across navigations (including the OIDC redirect through
// Keycloak), so attaching this once before any goto() captures console/
// pageerror output for the whole flow, not just the first document.
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

// PREVIOUSLY this comment claimed "visiting any protected route with no
// session triggers the Keycloak redirect directly (no in-app 'log in' link
// to click first)". Confirmed WRONG against a live deploy: opensearch_
// dashboards.yml.j2 sets opensearch_security.auth.type: "openid" (a single
// value, which should auto-redirect per the plugin's own docs), yet a live
// visit to `/` renders OpenSearch Dashboards' own /app/login shell and
// sits there - no navigation to openid-connect/auth occurs even after 20s
// of waiting. The exact reason wasn't pinned down further (not worth
// blocking this fix on), but the practical fix is the same generic,
// timing-tolerant trigger runAdminFlow already uses for exactly this
// situation across other apps (roles/test-e2e-playwright/files/personas/
// admin.js) - reused directly here rather than reimplemented, along with
// its performKeycloakLoginForm.
//
// The old version of this function had a second, more serious bug: its
// only success signal was `expect.poll(() => page.url()).toContain(host)`,
// which is trivially true even while sitting on /app/login (that IS on
// the app's own host) with zero credentials ever submitted. Confirmed
// empirically: a live run reported success while
// `page.context().cookies()` was `[]` - no session existed at all, and
// every test using this helper had actually never logged in. A real
// session cookie existing afterward is the one signal that distinguishes
// "genuinely authenticated" from "URL happens to match" - the second
// poll below is a direct, empirically-motivated fix for that failure mode.
async function wazuhLoginViaOidc(page, appBaseUrl, username, password) {
  await page.goto(`${appBaseUrl}/`, { waitUntil: "domcontentloaded" });

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
      timeout: 60_000,
      message: `Expected redirect back to ${appBaseUrl} after OIDC login`,
    })
    .toContain(new URL(appBaseUrl).host);
  await expect
    .poll(async () => (await page.context().cookies()).length, {
      timeout: 30_000,
      message:
        `Expected a real session cookie after OIDC login to ${appBaseUrl} ` +
        `(got 0 - the URL matched but no session was actually established)`,
    })
    .toBeGreaterThan(0);
}

// This role's own admin realm/client-id thin wrapper around the shared
// helper, so keycloakAdminAddUserToGroup/keycloakRemoveUserFromGroupViaRest
// below don't need to repeat it at every call site.
function keycloakAdminOpts() {
  return { adminRealm: env.keycloakAdminRealm, adminClientId: env.keycloakAdminCliClientId };
}

// Returns true when this call performed the join (caller MUST tear down),
// false when the user was already a member (caller MUST NOT remove it).
async function keycloakAdminAddUserToGroup(request, keycloakBaseUrl, realmName, targetGroupPath, username) {
  return keycloakAdmin.keycloakAdminAddUserToGroup(
    request,
    keycloakBaseUrl,
    realmName,
    targetGroupPath,
    username,
    env.superAdminUsername,
    env.superAdminPassword,
    keycloakAdminOpts(),
  );
}

async function keycloakRemoveUserFromGroupViaRest(request, keycloakBaseUrl, realmName, adminUsername, adminPassword, groupPath, username) {
  return keycloakAdmin.keycloakRemoveUserFromGroupViaRest(
    request,
    keycloakBaseUrl,
    realmName,
    adminUsername,
    adminPassword,
    groupPath,
    username,
    keycloakAdminOpts(),
  );
}

module.exports = {
  env,
  attachDiagnostics,
  wazuhLoginViaOidc,
  keycloakAdminAddUserToGroup,
  keycloakRemoveUserFromGroupViaRest,
};
