const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("./personas");
const keycloakAdmin = require("./personas/utils/keycloak");

const keycloakEnv = {
  keycloakBaseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || ""),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME),
  superAdminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME),
  superAdminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD),
  keycloakAdminRealm: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_REALM),
  keycloakAdminCliClientId: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
};

function adminOpts() {
  return { adminRealm: keycloakEnv.keycloakAdminRealm, adminClientId: keycloakEnv.keycloakAdminCliClientId };
}

/**
 * Run `fn` while biber is a member of the Keycloak group at `groupPath`,
 * removing the membership afterwards only when this call granted it.
 *
 * Args:
 *   browser: the Playwright browser, used for an isolated admin context.
 *   groupPath: the full Keycloak group path, with leading slash.
 *   fn: async body executed while the membership holds.
 */
async function withBiberInGroup(browser, groupPath, fn) {
  const adminCtx = await browser.newContext({ ignoreHTTPSErrors: true });
  let biberAdded = false;
  try {
    biberAdded = await keycloakAdmin.keycloakAdminAddUserToGroup(
      adminCtx.request,
      keycloakEnv.keycloakBaseUrl,
      keycloakEnv.realmName,
      groupPath,
      keycloakEnv.biberUsername,
      keycloakEnv.superAdminUsername,
      keycloakEnv.superAdminPassword,
      adminOpts(),
    );
    return await fn();
  } finally {
    if (biberAdded) {
      await keycloakAdmin
        .keycloakRemoveUserFromGroupViaRest(
          adminCtx.request,
          keycloakEnv.keycloakBaseUrl,
          keycloakEnv.realmName,
          keycloakEnv.superAdminUsername,
          keycloakEnv.superAdminPassword,
          groupPath,
          keycloakEnv.biberUsername,
          adminOpts(),
        )
        .catch((err) => console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`));
    }
    await adminCtx.close().catch(() => {});
  }
}

module.exports = { withBiberInGroup };
