const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  keycloakAdminAddUserToGroup,
  keycloakRemoveUserFromGroupViaRest,
  normalizeBaseUrl,
  performKeycloakLoginExpectingDenial,
  performKeycloakLoginForm,
  requireDotenvValue,
  withLdapGroupMember,
} = require("./personas");

const baseUrl = normalizeBaseUrl(
  requireDotenvValue(process.env.FUSIONDIRECTORY_BASE_URL, "FUSIONDIRECTORY_BASE_URL"),
).replace(/\/$/, "");
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
const keycloak = {
  baseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || ""),
  realm: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME || ""),
  username: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME || ""),
  password: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD || ""),
  opts: {
    adminRealm: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_REALM || ""),
    adminClientId: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID || ""),
  },
};
const biber = {
  username: decodeDotenvQuotedValue(process.env.BIBER_USERNAME || ""),
  password: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD || ""),
};
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const groups = {
  administrator: decodeDotenvQuotedValue(process.env.RBAC_ADMINISTRATOR_GROUP_PATH || ""),
  userManager: decodeDotenvQuotedValue(process.env.RBAC_USER_MANAGER_GROUP_PATH || ""),
  selfService: decodeDotenvQuotedValue(process.env.RBAC_SELF_SERVICE_GROUP_PATH || ""),
};
const directory = {
  biberDn: requireDotenvValue(process.env.BIBER_LDAP_DN, "BIBER_LDAP_DN"),
  administrator: requireDotenvValue(process.env.LDAP_ADMINISTRATOR_GROUP_DN, "LDAP_ADMINISTRATOR_GROUP_DN"),
  userManager: requireDotenvValue(process.env.LDAP_USER_MANAGER_GROUP_DN, "LDAP_USER_MANAGER_GROUP_DN"),
  selfService: requireDotenvValue(process.env.LDAP_SELF_SERVICE_GROUP_DN, "LDAP_SELF_SERVICE_GROUP_DN"),
};
const MENU = {
  users: /^Users$/,
  aclRoles: /^ACL roles$/,
  aclAssignments: /^ACL assignments$/,
  configuration: /^Configuration$/,
  myAccount: /^User$/,
};

function forgedHeaders(identity) {
  return {
    "X-Forwarded-Preferred-Username": identity,
    "X-Forwarded-User": identity,
    "X-Auth-Request-Preferred-Username": identity,
    "X-Auth-Request-User": identity,
    "Remote-User": identity,
  };
}

function menuEntry(page, label) {
  return page.locator('a[href*="plug="]', { hasText: label });
}

async function newContext(browser, extraHTTPHeaders) {
  return browser.newContext({ ignoreHTTPSErrors: true, ...(extraHTTPHeaders ? { extraHTTPHeaders } : {}) });
}

async function withBiberInGroup(browser, groupPath, body) {
  expect(groupPath, "the RBAC group path must be rendered").toBeTruthy();
  const adminCtx = await newContext(browser);
  let joined = false;
  try {
    joined = await keycloakAdminAddUserToGroup(
      adminCtx.request,
      keycloak.baseUrl,
      keycloak.realm,
      groupPath,
      biber.username,
      keycloak.username,
      keycloak.password,
      keycloak.opts,
    );
    await body();
  } finally {
    if (joined) {
      await keycloakRemoveUserFromGroupViaRest(
        adminCtx.request,
        keycloak.baseUrl,
        keycloak.realm,
        keycloak.username,
        keycloak.password,
        groupPath,
        biber.username,
        keycloak.opts,
      ).catch((err) => console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`));
    }
    await adminCtx.close().catch(() => {});
  }
}

async function signInAsBiber(page) {
  await gotoOnion(page, `${baseUrl}/`);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "expected the oauth2-proxy redirect to Keycloak" })
    .toContain("openid-connect/auth");
  await performKeycloakLoginForm(page, biber.username, biber.password);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(90_000), message: "expected the header login to open main.php" })
    .toContain(`${baseUrl}/main.php`);
  await expect(page.locator("div.plugin-window").first()).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function asBiberInGroup(browser, groupPath, body) {
  await withBiberInGroup(browser, groupPath, async () => {
    const ctx = await newContext(browser);
    try {
      const page = await ctx.newPage();
      await signInAsBiber(page);
      await body(page, ctx);
    } finally {
      await ctx.close().catch(() => {});
    }
  });
}

async function signInAsBiberThroughForm(page) {
  await gotoOnion(page, `${baseUrl}/index.php`, { waitUntil: "domcontentloaded" });
  const username = page.locator("#loginform input#username");
  await expect(username, "FusionDirectory must offer its own login form while SSO is disabled").toBeEditable({
    timeout: resolveTimeout(60_000),
  });
  await username.fill(biber.username);
  await page.locator("#loginform input#password").fill(biber.password);
  await page.locator('#loginform input[name="login"]').click();
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "expected the directory login to open main.php" })
    .toContain(`${baseUrl}/main.php`);
  await expect(page.locator("div.plugin-window").first()).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function asBiberInDirectoryGroup(browser, groupDn, body) {
  await withLdapGroupMember(groupDn, directory.biberDn, async () => {
    const ctx = await newContext(browser);
    try {
      const page = await ctx.newPage();
      await signInAsBiberThroughForm(page);
      await body(page);
    } finally {
      await ctx.close().catch(() => {});
    }
  });
}

async function expectAdministratorMenu(page) {
  for (const label of [MENU.users, MENU.aclAssignments, MENU.aclRoles, MENU.configuration]) {
    await expect(menuEntry(page, label), `an administrator group member must see the ${label} menu entry`).not.toHaveCount(0);
  }
}

async function expectUserManagerMenu(page) {
  await expect(menuEntry(page, MENU.users), "a user-manager must reach the user management").not.toHaveCount(0);
  for (const label of [MENU.aclAssignments, MENU.aclRoles, MENU.configuration]) {
    await expect(menuEntry(page, label), `a user-manager must not see the ${label} menu entry`).toHaveCount(0);
  }
}

async function expectSelfServiceAccount(page) {
  for (const label of [MENU.aclAssignments, MENU.aclRoles, MENU.configuration]) {
    await expect(menuEntry(page, label), `a self-service member must not see the ${label} menu entry`).toHaveCount(0);
  }
  const href = await menuEntry(page, MENU.myAccount).first().getAttribute("href");
  expect(href, "a self-service member must reach the own account").toBeTruthy();
  await gotoOnion(page, new URL(href, `${baseUrl}/`).href);
  await expect(
    page.locator('input[type="submit"][name="edit"]'),
    "the self-service ACL role must allow editing the own account",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
}

const ROLE_GROUPS = [
  {
    grant: "the administrator group grants the FusionDirectory admin ACL role",
    groupPath: () => groups.administrator,
    groupDn: () => directory.administrator,
    expectRights: expectAdministratorMenu,
  },
  {
    grant: "the user-manager group manages users without ACL or configuration rights",
    groupPath: () => groups.userManager,
    groupDn: () => directory.userManager,
    expectRights: expectUserManagerMenu,
  },
  {
    grant: "the self-service group edits the own account only",
    groupPath: () => groups.selfService,
    groupDn: () => directory.selfService,
    expectRights: expectSelfServiceAccount,
  },
];

async function keepOnlyProxySession(context) {
  const host = new URL(baseUrl).hostname;
  const cookies = await context.cookies();
  const kept = cookies.filter(
    (cookie) => cookie.name.startsWith("_oauth2_proxy") || !host.endsWith(cookie.domain.replace(/^\./, "")),
  );
  await context.clearCookies();
  await context.addCookies(kept);
}

exports.register = function () {
  test("rbac: biber without a FusionDirectory role is denied at the oauth2-proxy gate", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    await page.context().clearCookies();
    await gotoOnion(page, `${baseUrl}/`);
    await expect
      .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "expected the oauth2-proxy redirect to Keycloak" })
      .toContain("openid-connect/auth");
    await performKeycloakLoginExpectingDenial(page, biber.username, biber.password, canonicalDomain);
  });

  for (const role of ROLE_GROUPS) {
    test(`biber: ${role.grant} through the header login`, async ({ browser }) => {
      skipUnlessServiceEnabled("sso");
      await asBiberInGroup(browser, role.groupPath(), role.expectRights);
    });

    test(`biber: ${role.grant} through the directory login form`, async ({ browser }) => {
      skipUnlessServiceEnabled("ldap");
      skipUnlessServiceDisabled("sso");
      await asBiberInDirectoryGroup(browser, role.groupDn(), role.expectRights);
    });
  }

  test("oidc-security: a forged identity header cannot bypass the oauth2-proxy gate", async ({ browser }) => {
    skipUnlessServiceEnabled("sso");
    const ctx = await newContext(browser, forgedHeaders(adminUsername));
    try {
      const page = await ctx.newPage();
      await gotoOnion(page, `${baseUrl}/main.php`, { waitUntil: "domcontentloaded" });
      await expect
        .poll(() => page.url(), {
          timeout: resolveTimeout(60_000),
          message: "a forged identity header must be bounced to Keycloak, never into FusionDirectory",
        })
        .toContain("openid-connect/auth");
      await expect(page.locator("div.plugin-window"), "no FusionDirectory session may be minted from a forged header").toHaveCount(0);
    } finally {
      await ctx.close().catch(() => {});
    }
  });

  test("biber: a forged identity header cannot switch the header login identity", async ({ browser }) => {
    skipUnlessServiceEnabled("sso");
    await asBiberInGroup(browser, groups.selfService, async (page, ctx) => {
      await expect(menuEntry(page, MENU.aclRoles), "biber must start without admin rights").toHaveCount(0);
      await keepOnlyProxySession(ctx);
      await page.setExtraHTTPHeaders(forgedHeaders(adminUsername));
      await gotoOnion(page, `${baseUrl}/main.php`, { waitUntil: "domcontentloaded" });
      await expect(page.locator("div.plugin-window").first(), "the header login must reopen biber's session").toBeVisible({
        timeout: resolveTimeout(60_000),
      });
      for (const label of [MENU.aclRoles, MENU.configuration]) {
        await expect(
          menuEntry(page, label),
          `the oauth2-proxy identity must win; a forged header must not grant the ${label} menu entry`,
        ).toHaveCount(0);
      }
    });
  });

  test("oidc-security: the header login stays off while SSO is disabled", async ({ browser }) => {
    skipUnlessServiceDisabled("sso");
    const ctx = await newContext(browser, forgedHeaders(adminUsername));
    try {
      const page = await ctx.newPage();
      await gotoOnion(page, `${baseUrl}/index.php`, { waitUntil: "domcontentloaded" });
      await expect(page.locator("#loginform input#username"), "FusionDirectory must keep its own login form").toBeVisible({
        timeout: resolveTimeout(30_000),
      });
      await expect(page.locator("div.plugin-window"), "a forged identity header must never open a session").toHaveCount(0);
    } finally {
      await ctx.close().catch(() => {});
    }
  });
};
