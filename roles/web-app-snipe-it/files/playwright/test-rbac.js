const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const {
  normalizeBaseUrl,
  decodeDotenvQuotedValue,
  performKeycloakLoginForm,
  gotoOnion,
  requireDotenvValue,
  withLdapAttributes,
  withLdapGroupMember,
} = require("./personas");
const keycloakAdmin = require("./personas/utils/keycloak");

const env = {
  baseUrl: normalizeBaseUrl(process.env.SNIPE_IT_BASE_URL || ""),
  oidcIssuerUrl: normalizeBaseUrl(process.env.OIDC_ISSUER_URL || ""),
  keycloakBaseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || ""),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME || ""),
  keycloakAdminUsername: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_USERNAME || ""),
  keycloakAdminPassword: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_PASSWORD || ""),
  keycloakAdminRealm: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_REALM || ""),
  keycloakAdminCliClientId: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID || ""),
  administratorGroupPath: decodeDotenvQuotedValue(process.env.SNIPE_IT_ADMINISTRATOR_GROUP_PATH || ""),
  userGroupPath: decodeDotenvQuotedValue(process.env.SNIPE_IT_USER_GROUP_PATH || ""),
  permissionGroup: decodeDotenvQuotedValue(process.env.SNIPE_IT_USER_PERMISSION_GROUP || ""),
  protectedJson: decodeDotenvQuotedValue(process.env.SNIPE_IT_RBAC_PROTECTED_JSON || ""),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || ""),
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || ""),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME || ""),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD || ""),
};

const directory = {
  biberDn: requireDotenvValue(process.env.BIBER_LDAP_DN, "BIBER_LDAP_DN"),
  userGroupDn: requireDotenvValue(process.env.LDAP_USER_GROUP_DN, "LDAP_USER_GROUP_DN"),
  fieldMap: JSON.parse(requireDotenvValue(process.env.SNIPE_IT_LDAP_FIELD_MAP_JSON, "SNIPE_IT_LDAP_FIELD_MAP_JSON")),
};

const SNIPE_IT_FIELD_BY_SETTING = {
  ldap_display_name: "display_name",
  ldap_emp_num: "employee_num",
  ldap_phone_field: "phone",
  ldap_mobile: "mobile",
  ldap_jobtitle: "jobtitle",
  ldap_address: "address",
  ldap_city: "city",
  ldap_state: "state",
  ldap_zip: "zip",
  ldap_country: "country",
};

const adminOpts = () => ({ adminRealm: env.keycloakAdminRealm, adminClientId: env.keycloakAdminCliClientId });

test.use({ ignoreHTTPSErrors: true });

function expectEnv() {
  for (const [key, value] of Object.entries(env)) {
    expect(value, `${key} must be set`).toBeTruthy();
  }
}

async function signInThroughGate(page, username, password) {
  await gotoOnion(page, `${env.baseUrl}/login`, { waitUntil: "domcontentloaded" });
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected ${username} to be sent to Keycloak by the oauth2-proxy gate on /login`,
    })
    .toContain(`${env.oidcIssuerUrl}/protocol/openid-connect/auth`);
  await performKeycloakLoginForm(page, username, password);
}

const snipeItShell = (page) => page.locator(".main-header .navbar");
const directoryLoginForm = (page) => page.locator('form:has(input[name="password"])');

async function submitDirectoryLoginForm(page, username, password) {
  const form = directoryLoginForm(page);
  await form.locator('input[name="username"]').fill(username);
  await form.locator('input[name="password"]').fill(password);
  await form.locator('[type="submit"]').first().click({ timeout: resolveTimeout(30_000) });
}

async function reachSnipeItShell(page, username, password) {
  await signInThroughGate(page, username, password);
  const shell = snipeItShell(page);
  await expect(
    shell.or(directoryLoginForm(page)).first(),
    `expected ${username} to land on Snipe-IT, either signed in through the header bridge or on its directory login form`,
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
  if (!(await shell.isVisible())) {
    await submitDirectoryLoginForm(page, username, password);
  }
  await expect(shell, `expected ${username} to reach the Snipe-IT authenticated shell`).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
}

async function signInWithLoginForm(page, username, password) {
  await gotoOnion(page, `${env.baseUrl}/login`, { waitUntil: "domcontentloaded" });
  await expect(
    directoryLoginForm(page),
    "without SSO Snipe-IT must serve its own password and directory login form on /login",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
  await submitDirectoryLoginForm(page, username, password);
  await expect(snipeItShell(page), `expected ${username} to reach the Snipe-IT authenticated shell`).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
}

async function settingsStatus(page) {
  const response = await page.request.get(`${env.baseUrl}/admin`, { maxRedirects: 0 });
  return response.status();
}

async function snipeItApi(page, method, path, body) {
  return page.evaluate(
    async ({ method, path, body }) => {
      const csrf = document.querySelector('meta[name="csrf-token"]');
      const response = await fetch(path, {
        method,
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRF-TOKEN": csrf ? csrf.getAttribute("content") : "",
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      return { status: response.status, json: await response.json().catch(() => null) };
    },
    { method, path, body },
  );
}

async function snipeItUsers(page) {
  const result = await snipeItApi(page, "GET", "/api/v1/users?limit=500");
  expect(result.status, "the administrator session must read the Snipe-IT users API").toBe(200);
  return result.json.rows;
}

async function ldapTestLogin(page, username, password) {
  return snipeItApi(page, "POST", "/api/v1/settings/ldaptestlogin", {
    ldaptest_user: username,
    ldaptest_password: password,
  });
}

async function syncDirectoryAndFindBiber(page) {
  await gotoOnion(page, `${env.baseUrl}/users/ldap`, { waitUntil: "domcontentloaded" });
  await page.locator("#sync").click({ timeout: resolveTimeout(30_000) });
  const biberRow = page.locator("#customFieldsTable tbody tr").filter({ hasText: env.biberUsername }).first();
  await expect(biberRow, "the LDAP sync must import biber once biber holds the user role group").toBeVisible({
    timeout: resolveTimeout(120_000),
  });
  return biberRow;
}

async function keycloakGroupMembers(request, groupPath) {
  const token = await keycloakAdmin.keycloakAdminToken(
    request,
    env.keycloakBaseUrl,
    env.keycloakAdminUsername,
    env.keycloakAdminPassword,
    adminOpts(),
  );
  const groupId = await keycloakAdmin.keycloakResolveGroupId(request, env.keycloakBaseUrl, env.realmName, token, groupPath);
  const response = await request.get(
    `${env.keycloakBaseUrl}/admin/realms/${encodeURIComponent(env.realmName)}/groups/${groupId}/members?max=1000`,
    { headers: { Authorization: `Bearer ${token}` }, timeout: resolveTimeout(30_000) },
  );
  expect(response.ok(), `Keycloak members of ${groupPath} must be readable`).toBe(true);
  return (await response.json()).map((member) => member.username);
}

async function withContext(browser, fn) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    return await fn(await context.newPage());
  } finally {
    await context.close().catch(() => {});
  }
}

const isSuperuser = (user) => String((user.permissions || {}).superuser) === "1";
const holdsAdmin = (user) => String((user.permissions || {}).admin) === "1";
const inPermissionGroup = (user) =>
  Boolean(user.groups && user.groups.rows.some((group) => group.name === env.permissionGroup));

test("biber: the proxy refuses a persona holding none of the Snipe-IT role groups", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(env.baseUrl, "SNIPE_IT_BASE_URL must be set").toBeTruthy();
  expect(env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

  await signInThroughGate(page, env.biberUsername, env.biberPassword);

  await expect(page.locator(".main-header .navbar"), {
    message:
      "biber reached the Snipe-IT shell; meta/services.yml admits only the administrator and user role groups and biber holds neither",
  }).toHaveCount(0, { timeout: resolveTimeout(30_000) });
  await expect(page.locator("body"), {
    message: "the page is neither Snipe-IT nor a recognisable denial; the proxy may have changed its rejection wording",
  }).toContainText(/403|forbidden|permission|unauthorized|access denied/i, { timeout: resolveTimeout(60_000) });
});

test("administrator: the deploy-time reconcile leaves superuser and the permission group only on role-group members", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000)); // one Keycloak sign-in plus the Keycloak admin token and member reads
  expectEnv();
  const protectedUsernames = JSON.parse(env.protectedJson);

  const adminRequest = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const administrators = await keycloakGroupMembers(adminRequest.request, env.administratorGroupPath);
    const members = new Set([...administrators, ...(await keycloakGroupMembers(adminRequest.request, env.userGroupPath))]);

    await withContext(browser, async (page) => {
      await reachSnipeItShell(page, env.adminUsername, env.adminPassword);
      expect(await settingsStatus(page), "the bootstrap administrator must reach the Snipe-IT settings at /admin").toBe(200);

      const accounts = (await snipeItUsers(page)).filter((user) => !protectedUsernames.includes(user.username));
      const usernames = new Set(accounts.map((user) => user.username));
      const missing = [...members].filter((username) => !protectedUsernames.includes(username) && !usernames.has(username));
      expect(missing, "every role-group member must have a Snipe-IT account after the deploy").toEqual([]);

      const strayAdmins = accounts
        .filter((user) => (isSuperuser(user) || holdsAdmin(user)) && !administrators.includes(user.username))
        .map((user) => user.username);
      expect(strayAdmins, "rbac_sync.php must demote every superuser or admin outside the administrator role group").toEqual([]);

      const unpromoted = accounts
        .filter((user) => administrators.includes(user.username) && !isSuperuser(user))
        .map((user) => user.username);
      expect(unpromoted, "rbac_sync.php must promote every administrator role-group member to superuser").toEqual([]);

      const ungrouped = accounts
        .filter((user) => members.has(user.username) && !inPermissionGroup(user))
        .map((user) => user.username);
      expect(ungrouped, `every role-group member must join the ${env.permissionGroup} permission group`).toEqual([]);
    });
  } finally {
    await adminRequest.close().catch(() => {});
  }
});

async function biberIsAdmittedThroughTheGate(browser) {
  test.setTimeout(resolveTimeout(300_000)); // two Keycloak sign-ins plus the LDAP sync POST, which rewrites every directory member
  expectEnv();

  const adminRequest = await browser.newContext({ ignoreHTTPSErrors: true });
  let biberJoined = false;
  try {
    biberJoined = await keycloakAdmin.keycloakAdminAddUserToGroup(
      adminRequest.request,
      env.keycloakBaseUrl,
      env.realmName,
      env.userGroupPath,
      env.biberUsername,
      env.keycloakAdminUsername,
      env.keycloakAdminPassword,
      adminOpts(),
    );

    await withContext(browser, async (page) => {
      await reachSnipeItShell(page, env.adminUsername, env.adminPassword);
      await syncDirectoryAndFindBiber(page);
    });

    await withContext(browser, async (page) => {
      await reachSnipeItShell(page, env.biberUsername, env.biberPassword);
      expect(
        await settingsStatus(page),
        "biber holds only the user role group and must not reach the Snipe-IT settings at /admin",
      ).not.toBe(200);
    });
  } finally {
    if (biberJoined) {
      await keycloakAdmin
        .keycloakRemoveUserFromGroupViaRest(
          adminRequest.request,
          env.keycloakBaseUrl,
          env.realmName,
          env.keycloakAdminUsername,
          env.keycloakAdminPassword,
          env.userGroupPath,
          env.biberUsername,
          adminOpts(),
        )
        .catch((err) => console.warn(`Cleanup removal of biber from ${env.userGroupPath} failed: ${err}`));
    }
    await adminRequest.close().catch(() => {});
  }
}

async function biberIsAdmittedThroughTheDirectoryLogin(browser) {
  test.setTimeout(resolveTimeout(360_000)); // two form sign-ins plus the LDAP sync POST, which rewrites every directory member
  expect(
    Object.keys(directory.fieldMap).sort(),
    "SNIPE_IT_LDAP_FIELD_MAP_JSON must map exactly the directory settings this test writes",
  ).toEqual([...Object.keys(SNIPE_IT_FIELD_BY_SETTING), "ldap_dept"].sort());

  const marker = Date.now().toString(36);
  const digits = String(Date.now()).slice(-7);
  const profile = {
    ldap_display_name: `Biber ${marker}`,
    ldap_emp_num: `E-${marker}`,
    ldap_phone_field: `+49 30 ${digits}`,
    ldap_mobile: `+49 170 ${digits}`,
    ldap_jobtitle: `Asset keeper ${marker}`,
    ldap_dept: `Inventory ${marker}`,
    ldap_address: `Biberweg ${marker}`,
    ldap_city: `Biberstadt ${marker}`,
    ldap_state: `Biberland ${marker}`,
    ldap_zip: `P${digits}`,
    ldap_country: "IS",
  };
  const attributes = Object.fromEntries(
    Object.entries(profile).map(([setting, value]) => [directory.fieldMap[setting], value]),
  );

  await withLdapAttributes(directory.biberDn, attributes, () =>
    withContext(browser, async (page) => {
      await signInWithLoginForm(page, env.adminUsername, env.adminPassword);

      const refusedBiber = await ldapTestLogin(page, env.biberUsername, env.biberPassword);
      expect(refusedBiber.status, "the Snipe-IT LDAP filter must refuse biber while biber holds no role group").toBe(400);
      expect(String((refusedBiber.json || {}).message)).toMatch(/did not successfully bind/i);

      await withLdapGroupMember(directory.userGroupDn, directory.biberDn, async () => {
        const admittedBiber = await ldapTestLogin(page, env.biberUsername, env.biberPassword);
        expect(admittedBiber.status, "the Snipe-IT LDAP filter must admit biber once biber holds the user role group").toBe(200);

        const biberRow = await syncDirectoryAndFindBiber(page);
        await expect(biberRow).toContainText(profile.ldap_display_name);
        await expect(biberRow).toContainText(profile.ldap_emp_num);

        const biber = (await snipeItUsers(page)).find((user) => user.username === env.biberUsername);
        expect(biber, "the LDAP sync must leave a Snipe-IT account for biber").toBeTruthy();
        for (const [setting, field] of Object.entries(SNIPE_IT_FIELD_BY_SETTING)) {
          expect(biber[field], `Snipe-IT field ${field} must carry the directory value of ${directory.fieldMap[setting]}`).toBe(
            profile[setting],
          );
        }
        expect((biber.department || {}).name, "Snipe-IT must file biber under the directory department").toBe(profile.ldap_dept);

        await gotoOnion(page, `${env.baseUrl}/users/${biber.id}`, { waitUntil: "domcontentloaded" });
        await expect(page.locator("body"), "the user page must show the directory phone").toContainText(profile.ldap_phone_field);
        await expect(page.locator("body"), "the user page must show the directory job title").toContainText(profile.ldap_jobtitle);

        await withContext(browser, async (biberPage) => {
          await signInWithLoginForm(biberPage, env.biberUsername, env.biberPassword);
          expect(
            await settingsStatus(biberPage),
            "biber holds only the user role group and must not reach the Snipe-IT settings at /admin",
          ).not.toBe(200);
        });
      });
    }),
  );
}

test("administrator: the LDAP filter leaves the bootstrap administrator out while its own sign-in keeps the Snipe-IT settings", async ({ browser }) => {
  skipUnlessServiceEnabled("ldap");
  await withContext(browser, async (page) => {
    if (isServiceEnabled("sso")) {
      await reachSnipeItShell(page, env.adminUsername, env.adminPassword);
    } else {
      await signInWithLoginForm(page, env.adminUsername, env.adminPassword);
    }
    expect(await settingsStatus(page), "the bootstrap administrator must reach the Snipe-IT settings at /admin").toBe(200);

    const refusedAdmin = await ldapTestLogin(page, env.adminUsername, env.adminPassword);
    expect(refusedAdmin.status, "the Snipe-IT LDAP filter must leave out the bootstrap administrator").toBe(400);
    expect(String((refusedAdmin.json || {}).message)).toMatch(/did not successfully bind/i);
  });
});

test("biber: the user role group admits biber once the directory account reaches Snipe-IT, with no admin rights", async ({ browser }) => {
  skipUnlessServiceEnabled("ldap");
  if (isServiceEnabled("sso")) {
    await biberIsAdmittedThroughTheGate(browser);
  } else {
    await biberIsAdmittedThroughTheDirectoryLogin(browser);
  }
});
