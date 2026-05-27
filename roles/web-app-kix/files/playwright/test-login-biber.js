const { test, expect, request } = require("@playwright/test");

const { decodeDotenvQuotedValue } = require("./personas");

const kcBaseUrl        = decodeDotenvQuotedValue(process.env.KEYCLOAK_BASE_URL     || "").replace(/\/$/, "");
const kcRealm          = decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM        || "");
const kcAdminUser      = decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_USERNAME || "");
const kcAdminPw        = decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_PASSWORD || "");
const kixUserGroupPath = decodeDotenvQuotedValue(process.env.KIX_USER_GROUP_PATH   || "");
const biberUsername    = decodeDotenvQuotedValue(process.env.BIBER_USERNAME        || "");
const biberPassword    = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD        || "");

async function ensureUserInGroup(username, groupPath) {
  const api = await request.newContext({ ignoreHTTPSErrors: true });

  const tokenResp = await api.post(
    `${kcBaseUrl}/realms/master/protocol/openid-connect/token`,
    {
      form: {
        client_id: "admin-cli",
        username:  kcAdminUser,
        password:  kcAdminPw,
        grant_type: "password",
      },
    },
  );
  if (!tokenResp.ok()) {
    throw new Error(`Keycloak admin token failed: ${tokenResp.status()} ${await tokenResp.text()}`);
  }
  const accessToken = (await tokenResp.json()).access_token;
  const auth = { Authorization: `Bearer ${accessToken}` };

  const usersResp = await api.get(
    `${kcBaseUrl}/admin/realms/${kcRealm}/users?username=${encodeURIComponent(username)}&exact=true`,
    { headers: auth },
  );
  if (!usersResp.ok()) {
    throw new Error(`Keycloak user lookup failed: ${usersResp.status()} ${await usersResp.text()}`);
  }
  const users = await usersResp.json();
  if (!users.length) {
    throw new Error(`Keycloak user '${username}' not found in realm ${kcRealm}`);
  }
  const userId = users[0].id;

  const groupResp = await api.get(
    `${kcBaseUrl}/admin/realms/${kcRealm}/group-by-path${groupPath}`,
    { headers: auth },
  );
  if (!groupResp.ok()) {
    throw new Error(`Keycloak group lookup failed for ${groupPath}: ${groupResp.status()} ${await groupResp.text()}`);
  }
  const group = await groupResp.json();
  const groupId = group.id;

  const putResp = await api.put(
    `${kcBaseUrl}/admin/realms/${kcRealm}/users/${userId}/groups/${groupId}`,
    { headers: auth },
  );
  if (![200, 204].includes(putResp.status())) {
    throw new Error(`Keycloak group assignment failed: ${putResp.status()} ${await putResp.text()}`);
  }

  await api.dispose();
}

exports.register = function (shared) {
  test("biber (granted web-app-kix-user via Keycloak): full login flow (KIX → OAuth2-proxy → Keycloak → KIX-LDAP login → KIX UI → universal logout)", async ({ page }) => {
    test.skip(!shared.env.oauth2Enabled, "OAuth2 shared service disabled");
    test.skip(!shared.env.ldapEnabled,   "LDAP shared service disabled");
    expect(kcBaseUrl,        "KEYCLOAK_BASE_URL must be set").toBeTruthy();
    expect(kcRealm,          "KEYCLOAK_REALM must be set").toBeTruthy();
    expect(kcAdminUser,      "KEYCLOAK_ADMIN_USERNAME must be set").toBeTruthy();
    expect(kcAdminPw,        "KEYCLOAK_ADMIN_PASSWORD must be set").toBeTruthy();
    expect(kixUserGroupPath, "KIX_USER_GROUP_PATH must be set").toBeTruthy();
    expect(biberUsername,    "BIBER_USERNAME must be set").toBeTruthy();
    expect(biberPassword,    "BIBER_PASSWORD must be set").toBeTruthy();

    await ensureUserInGroup(biberUsername, kixUserGroupPath);
    await shared.runKixLoginLogoutFlow(page, biberUsername, biberPassword);
  });
};
