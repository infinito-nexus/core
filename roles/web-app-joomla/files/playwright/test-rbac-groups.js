const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
  installCspViolationObserver,
  keycloakAdminAddUserToGroup,
  keycloakRemoveUserFromGroupViaRest,
  normalizeBaseUrl,
  requireDotenvValue,
} = require("./personas");
const { signInToAdministrator, signInViaKeycloak, userManagerRow } = require("./joomla-session");

const base = normalizeBaseUrl(process.env.JOOMLA_BASE_URL);
const keycloakBaseUrl = normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL);
const realmName = decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME);
const superAdminUsername = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME);
const superAdminPassword = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD);
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const groupPaths = JSON.parse(requireDotenvValue(process.env.JOOMLA_RBAC_GROUPS_JSON, "JOOMLA_RBAC_GROUPS_JSON"));

const JOOMLA_GROUP_TITLES = {
  administrator: "Super Users",
  manager: "Manager",
  publisher: "Publisher",
  editor: "Editor",
  author: "Author",
  registered: "Registered",
};

test.use({ ignoreHTTPSErrors: true });

async function newContext(browser) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  await installCspViolationObserver(page);
  return { context, page };
}

async function closeSignedOut(context) {
  await context.clearCookies().catch(() => {});
  await context.close().catch(() => {});
}

async function signsInViaKeycloak(browser, username, password) {
  const session = await newContext(browser);
  try {
    await signInViaKeycloak(session.page, base, username, password);
  } finally {
    await closeSignedOut(session.context);
  }
}

async function expectJoomlaGroup(browser, username, title) {
  const admin = await newContext(browser);
  try {
    await signInToAdministrator(admin.page, base, adminUsername, adminPassword);
    const row = await userManagerRow(admin.page, base, username);
    await expect(row, `Users: Manage must show ${username} in the Joomla group "${title}"`).toContainText(title, {
      timeout: resolveTimeout(30_000),
    });
  } finally {
    await closeSignedOut(admin.context);
  }
}

async function addToGroup(request, groupPath, username) {
  return keycloakAdminAddUserToGroup(
    request,
    keycloakBaseUrl,
    realmName,
    groupPath,
    username,
    superAdminUsername,
    superAdminPassword,
  );
}

async function removeFromGroup(request, groupPath, username) {
  await keycloakRemoveUserFromGroupViaRest(
    request,
    keycloakBaseUrl,
    realmName,
    superAdminUsername,
    superAdminPassword,
    groupPath,
    username,
  );
}

function requireGroupPath(role) {
  const groupPath = groupPaths[role];
  expect(groupPath, `JOOMLA_RBAC_GROUPS_JSON must carry the ${role} group path`).toBeTruthy();
  return groupPath;
}

test.describe.serial("rbac: Keycloak groups drive Joomla user groups", () => {
  for (const [role, title] of Object.entries(JOOMLA_GROUP_TITLES)) {
    test(`rbac: membership in the ${role} group grants the Joomla ${title} group`, async ({ browser }) => {
      skipUnlessServiceEnabled("sso");
      test.setTimeout(resolveTimeout(240_000));
      expect(base, "JOOMLA_BASE_URL must be set").toBeTruthy();
      const groupPath = requireGroupPath(role);

      const keycloak = await browser.newContext({ ignoreHTTPSErrors: true });
      let joined = false;
      try {
        joined = await addToGroup(keycloak.request, groupPath, biberUsername);
        await signsInViaKeycloak(browser, biberUsername, biberPassword);
        await expectJoomlaGroup(browser, biberUsername, title);
      } finally {
        if (joined) {
          await removeFromGroup(keycloak.request, groupPath, biberUsername).catch((error) =>
            console.warn(`Removing ${biberUsername} from ${groupPath} failed: ${error}`),
          );
        }
        await keycloak.close().catch(() => {});
      }
    });
  }

  test("rbac: the bootstrap administrator keeps Super Users without the administrator group", async ({ browser }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(240_000));
    const groupPath = requireGroupPath("administrator");

    const keycloak = await browser.newContext({ ignoreHTTPSErrors: true });
    let wasMember = false;
    try {
      wasMember = !(await addToGroup(keycloak.request, groupPath, adminUsername));
      await removeFromGroup(keycloak.request, groupPath, adminUsername);
      await signsInViaKeycloak(browser, adminUsername, adminPassword);
      await expectJoomlaGroup(browser, adminUsername, "Super Users");
    } finally {
      if (wasMember) {
        await addToGroup(keycloak.request, groupPath, adminUsername).catch((error) =>
          console.warn(`Restoring ${adminUsername} in ${groupPath} failed: ${error}`),
        );
      }
      await keycloak.close().catch(() => {});
    }
  });

  test("rbac: biber without a Joomla role group signs in and lands in Registered", async ({ browser }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(180_000));
    expect(base, "JOOMLA_BASE_URL must be set").toBeTruthy();
    await signsInViaKeycloak(browser, biberUsername, biberPassword);
    await expectJoomlaGroup(browser, biberUsername, "Registered");
  });
});
