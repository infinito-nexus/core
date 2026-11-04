const { test, expect } = require("./onion-test");
const { resolveTimeout } = require("./timeouts");

const {
  decodeDotenvQuotedValue,
  keycloakAdminAddUserToGroup,
  keycloakRemoveUserFromGroupViaRest,
  normalizeBaseUrl,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  adminUsername,
  adminPassword,
  biberUsername,
  biberPassword,
  logoutThroughAccountMenu,
  ownRoleIds,
  ssoLogin,
} = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

const OPENCLOUD_ROLE_IDS = {
  admin: "71881883-1768-46bd-a24d-a356a2afdf7f",
  spaceadmin: "2aadd357-682c-406b-8874-293091995fdd",
  user: "d7beeea8-8ff4-406b-8fb6-ab2dd81e6b11",
  "user-light": "38071a68-456a-4553-846a-fa67bf5596cc",
};

const env = {
  keycloakBaseUrl: normalizeBaseUrl(decodeDotenvQuotedValue(process.env.KEYCLOAK_BASE_URL) || ""),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME),
  adminRealm: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_REALM),
  adminClientId: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID),
  superAdminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME),
  superAdminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD),
};

const PROMOTIONS = [
  { group: "administrator", groupPath: decodeDotenvQuotedValue(process.env.RBAC_ADMINISTRATOR_GROUP_PATH), role: "admin" },
  { group: "spaceadmin", groupPath: decodeDotenvQuotedValue(process.env.RBAC_SPACEADMIN_GROUP_PATH), role: "spaceadmin" },
  { group: "guest", groupPath: decodeDotenvQuotedValue(process.env.RBAC_GUEST_GROUP_PATH), role: "user-light" },
];

async function signedInRoleIds(browser, username, password) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await context.newPage();
    await ssoLogin(page, username, password);
    const roleIds = await ownRoleIds(page);
    await logoutThroughAccountMenu(page);
    return roleIds;
  } finally {
    await context.close().catch(() => {});
  }
}

test("rbac: biber without a role group signs in to OpenCloud with the User role", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  expect(
    await signedInRoleIds(browser, biberUsername, biberPassword),
    "default-roles-<realm> must map every realm user without a role group to the OpenCloud User role",
  ).toEqual([OPENCLOUD_ROLE_IDS.user]);
});

test("rbac: the administrator holds the OpenCloud Admin role", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  expect(
    await signedInRoleIds(browser, adminUsername, adminPassword),
    "the administrator role group must map to the OpenCloud Admin role",
  ).toEqual([OPENCLOUD_ROLE_IDS.admin]);
});

for (const promotion of PROMOTIONS) {
  test(`rbac: membership in the ${promotion.group} group gives biber the OpenCloud ${promotion.role} role`, async ({ browser }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(240_000));
    const adminOpts = { adminRealm: env.adminRealm, adminClientId: env.adminClientId };
    const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });
    let joined = false;
    try {
      joined = await keycloakAdminAddUserToGroup(
        adminContext.request,
        env.keycloakBaseUrl,
        env.realmName,
        promotion.groupPath,
        biberUsername,
        env.superAdminUsername,
        env.superAdminPassword,
        adminOpts,
      );
      expect(
        await signedInRoleIds(browser, biberUsername, biberPassword),
        `biber in ${promotion.groupPath} must sign in with the OpenCloud ${promotion.role} role`,
      ).toEqual([OPENCLOUD_ROLE_IDS[promotion.role]]);
    } finally {
      if (joined) {
        await keycloakRemoveUserFromGroupViaRest(
          adminContext.request,
          env.keycloakBaseUrl,
          env.realmName,
          env.superAdminUsername,
          env.superAdminPassword,
          promotion.groupPath,
          biberUsername,
          adminOpts,
        ).catch((err) => console.warn(`Cleanup removal of biber from ${promotion.groupPath} failed: ${err}`));
      }
      await adminContext.close().catch(() => {});
    }
    expect(
      await signedInRoleIds(browser, biberUsername, biberPassword),
      `leaving ${promotion.groupPath} must give biber the OpenCloud User role back at the next sign-in`,
    ).toEqual([OPENCLOUD_ROLE_IDS.user]);
  });
}
