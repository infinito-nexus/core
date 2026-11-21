const {
  decodeDotenvQuotedValue,
  keycloakAdminToken,
  keycloakResolveGroupId,
  normalizeBaseUrl,
} = require("./personas");
const { resolveTimeout } = require("./timeouts");

function json(value) {
  const raw = decodeDotenvQuotedValue(value);
  return raw ? JSON.parse(raw) : {};
}

const env = {
  appBaseUrl: normalizeBaseUrl(decodeDotenvQuotedValue(process.env.APP_BASE_URL)),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN),
  targetApp: decodeDotenvQuotedValue(process.env.ACCESS_REQUEST_TARGET_APP),
  targetUrl: normalizeBaseUrl(decodeDotenvQuotedValue(process.env.ACCESS_REQUEST_TARGET_URL)),
  adminGroup: decodeDotenvQuotedValue(process.env.ACCESS_REQUEST_ADMIN_GROUP),
  otherAppGroup: decodeDotenvQuotedValue(process.env.ACCESS_REQUEST_OTHER_APP_GROUP),
  keptRole: json(process.env.ACCESS_REQUEST_KEPT_ROLE_JSON),
  droppedRole: json(process.env.ACCESS_REQUEST_DROPPED_ROLE_JSON),
  fourEyes: process.env.ACCESS_REQUEST_FOUR_EYES === "true",
  keycloakBaseUrl: normalizeBaseUrl(decodeDotenvQuotedValue(process.env.KEYCLOAK_BASE_URL)),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME),
  superAdminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME),
  superAdminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  mapacheUsername: decodeDotenvQuotedValue(process.env.MAPACHE_USERNAME),
};

/**
 * Args:
 *   request: an APIRequestContext.
 *   username: the realm user to look up with the bootstrap admin.
 * Returns `{ token, user, groups }`: the admin token, the user and the paths of its groups.
 */
async function realmUser(request, username) {
  const token = await keycloakAdminToken(
    request,
    env.keycloakBaseUrl,
    env.superAdminUsername,
    env.superAdminPassword,
  );
  const headers = { Authorization: `Bearer ${token}` };
  const base = `${env.keycloakBaseUrl}/admin/realms/${encodeURIComponent(env.realmName)}`;
  const users = await (
    await request.get(`${base}/users?username=${encodeURIComponent(username)}&exact=true`, {
      headers,
      timeout: resolveTimeout(30_000),
    })
  ).json();
  const user = users.find((u) => u.username === username);
  const groups = await (
    await request.get(`${base}/users/${user.id}/groups`, { headers, timeout: resolveTimeout(30_000) })
  ).json();
  return { token, user, groups: groups.map((g) => g.path) };
}

/**
 * Args:
 *   request: an APIRequestContext.
 *   token: the access token to act with.
 *   userId: Keycloak id of the user to add.
 *   groupPath: the group to join.
 * Returns the HTTP status Keycloak answered the join with.
 */
async function joinWith(request, token, userId, groupPath) {
  const superToken = await keycloakAdminToken(
    request,
    env.keycloakBaseUrl,
    env.superAdminUsername,
    env.superAdminPassword,
  );
  const groupId = await keycloakResolveGroupId(
    request,
    env.keycloakBaseUrl,
    env.realmName,
    superToken,
    groupPath,
  );
  const response = await request.put(
    `${env.keycloakBaseUrl}/admin/realms/${encodeURIComponent(env.realmName)}/users/${userId}/groups/${groupId}`,
    { headers: { Authorization: `Bearer ${token}` }, timeout: resolveTimeout(30_000) },
  );
  return response.status();
}

module.exports = { env, joinWith, realmUser };
