const { test, expect } = require("@playwright/test");
const {
  keycloakAdminAddUserToGroup,
  keycloakAdminToken,
  keycloakRemoveUserFromGroupViaRest,
} = require("./personas");

function register({ env, joinWith, realmUser }) {
  test("an application administrator grants only that application's non-administrator roles", async ({ request }) => {
    test.skip(!env.targetApp || !env.otherAppGroup, "needs a restricted application and a second application with a non-administrator role");

    const joined = await keycloakAdminAddUserToGroup(request, env.keycloakBaseUrl, env.realmName, env.adminGroup, env.biberUsername, env.superAdminUsername, env.superAdminPassword);
    const { user: mapache, groups: before } = await realmUser(request, env.mapacheUsername);
    const granted = [];
    try {
      const biberToken = await keycloakAdminToken(request, env.keycloakBaseUrl, env.biberUsername, env.biberPassword, { adminRealm: env.realmName });

      expect(await joinWith(request, biberToken, mapache.id, env.adminGroup), "the application's administrator role").toBe(403);
      expect(await joinWith(request, biberToken, mapache.id, env.otherAppGroup), "a role of another application").toBe(403);
      const own = await joinWith(request, biberToken, mapache.id, env.keptRole.path);
      if (!before.includes(env.keptRole.path)) granted.push(env.keptRole.path);
      expect(own, "a non-administrator role of the application").toBe(204);
    } finally {
      for (const path of granted) {
        await keycloakRemoveUserFromGroupViaRest(request, env.keycloakBaseUrl, env.realmName, env.superAdminUsername, env.superAdminPassword, path, env.mapacheUsername);
      }
      if (joined) {
        await keycloakRemoveUserFromGroupViaRest(request, env.keycloakBaseUrl, env.realmName, env.superAdminUsername, env.superAdminPassword, env.adminGroup, env.biberUsername);
      }
    }
  });
}

module.exports = { register };
