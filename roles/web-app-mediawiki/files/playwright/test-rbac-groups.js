const { test, expect } = require("@playwright/test");
const { resolveTimeout, isSplitRealmOidc } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  decodeDotenvJsonList,
  gotoOnion,
  keycloakAdminAddUserToGroup,
  keycloakRemoveUserFromGroupViaRest,
  normalizeUrl,
  readEnv,
} = require("./personas");
const { signInViaOidc: signInToWiki } = require("./mediawiki-session");

const env = {
  base: normalizeUrl(process.env.APP_BASE_URL),
  canonicalDomain: readEnv("CANONICAL_DOMAIN"),
  keycloakBaseUrl: normalizeUrl(process.env.KEYCLOAK_BASE_URL),
  realmName: readEnv("KEYCLOAK_REALM_NAME"),
  superAdminUsername: readEnv("SUPER_ADMIN_USERNAME"),
  superAdminPassword: readEnv("SUPER_ADMIN_PASSWORD"),
  biberUsername: readEnv("BIBER_USERNAME"),
  biberPassword: readEnv("BIBER_PASSWORD"),
};

const GROUP_MAP = decodeDotenvJsonList(process.env.RBAC_GROUP_MAP_JSON, "RBAC_GROUP_MAP_JSON");
const WIKI_GROUPS = GROUP_MAP.map((entry) => entry.group);
const ROLE_PATHS = [...new Set(GROUP_MAP.flatMap((entry) => entry.paths))];
const CLEANUP_DEADLINE_MS = 30_000;

function grantedBy(path) {
  return GROUP_MAP.filter((entry) => entry.paths.includes(path)).map((entry) => entry.group);
}

function withDeadline(promise, label) {
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} exceeded its deadline`)), resolveTimeout(CLEANUP_DEADLINE_MS));
  });
  return Promise.race([promise, deadline]).finally(() => clearTimeout(timer));
}

async function signInViaOidc(page, username, password) {
  await signInToWiki(page, env.base, env.canonicalDomain, username, password);
}

async function wikiGroupsOf(page, username) {
  const held = [];
  for (const group of WIKI_GROUPS) {
    await gotoOnion(page, `${env.base}/index.php?title=Special:ListUsers&group=${encodeURIComponent(group)}&limit=500`, {
      waitUntil: "domcontentloaded",
    });
    const list = page.locator("#mw-content-text");
    await expect(list, `Special:ListUsers MUST render for group ${group}`).toBeVisible({
      timeout: resolveTimeout(30_000),
    });
    const userLink = list.locator("a.mw-userlink").filter({ hasText: new RegExp(`^${username}$`, "i") });
    if ((await userLink.count()) > 0) held.push(group);
  }
  return held.sort();
}

async function groupsAfterLogin(browser) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await context.newPage();
    await signInViaOidc(page, env.biberUsername, env.biberPassword);
    return await wikiGroupsOf(page, env.biberUsername);
  } finally {
    await context.close().catch(() => {});
  }
}

test("administrator: the OIDC login adopts the provisioned local account and maps administrator onto every admin group", async ({
  browser,
}) => {
  skipUnlessServiceEnabled("sso");
  test.skip(isSplitRealmOidc(), "clearnet app with an onion OIDC issuer: unreachable from one browser");
  test.setTimeout(resolveTimeout(240_000));
  const adminUsername = readEnv("ADMIN_USERNAME");
  const adminPassword = readEnv("ADMIN_PASSWORD");
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  const wikiName = adminUsername.charAt(0).toUpperCase() + adminUsername.slice(1);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await context.newPage();
    await signInViaOidc(page, adminUsername, adminPassword);

    const response = await gotoOnion(page, `${env.base}/api.php?action=query&meta=userinfo&format=json`, {
      waitUntil: "domcontentloaded",
    });
    expect(response, "api.php MUST answer the userinfo query").toBeTruthy();
    const userinfo = (await response.json()).query.userinfo;
    expect(
      userinfo.name,
      `the OIDC login of ${adminUsername} MUST land on the local account createAndPromote provisioned, not on a numbered copy`,
    ).toBe(wikiName);

    expect(
      await wikiGroupsOf(page, adminUsername),
      `${adminUsername} holds the administrator role group, so the OIDC login MUST leave every mapped admin group`,
    ).toEqual([...WIKI_GROUPS].sort());
  } finally {
    await context.close().catch(() => {});
  }
});

for (const rolePath of ROLE_PATHS) {
  test(`biber: membership in ${rolePath} grants the mapped wiki groups at OIDC login`, async ({ browser }) => {
    skipUnlessServiceEnabled("sso");
    test.skip(isSplitRealmOidc(), "clearnet app with an onion OIDC issuer: unreachable from one browser");
    test.setTimeout(resolveTimeout(300_000));
    for (const [name, value] of Object.entries(env)) {
      expect(value, `${name} must be set`).toBeTruthy();
    }

    const expected = grantedBy(rolePath).sort();
    const api = await browser.newContext({ ignoreHTTPSErrors: true });
    let joined = false;
    try {
      joined = await keycloakAdminAddUserToGroup(
        api.request,
        env.keycloakBaseUrl,
        env.realmName,
        rolePath,
        env.biberUsername,
        env.superAdminUsername,
        env.superAdminPassword,
      );
      expect(
        await groupsAfterLogin(browser),
        `${env.biberUsername} holds only ${rolePath}, so the OIDC login MUST leave exactly these wiki groups`,
      ).toEqual(expected);

      if (!joined) return;

      await keycloakRemoveUserFromGroupViaRest(
        api.request,
        env.keycloakBaseUrl,
        env.realmName,
        env.superAdminUsername,
        env.superAdminPassword,
        rolePath,
        env.biberUsername,
      );
      joined = false;

      expect(
        await groupsAfterLogin(browser),
        `${env.biberUsername} left ${rolePath}, so the next OIDC login MUST revoke every mapped wiki group`,
      ).toEqual([]);
    } finally {
      if (joined) {
        await withDeadline(
          keycloakRemoveUserFromGroupViaRest(
            api.request,
            env.keycloakBaseUrl,
            env.realmName,
            env.superAdminUsername,
            env.superAdminPassword,
            rolePath,
            env.biberUsername,
          ),
          "group cleanup",
        ).catch((err) => console.warn(`Cleanup removal of ${env.biberUsername} from ${rolePath} failed: ${err}`));
      }
      await api.close().catch(() => {});
    }
  });
}
