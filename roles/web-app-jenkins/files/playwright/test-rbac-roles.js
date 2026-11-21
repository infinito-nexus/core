const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl, gotoOnion } = require("./personas");
const keycloakAdmin = require("./personas/utils/keycloak");
const { baseUrl, loginAs, loginAsAdministrator, whoAmI } = require("./jenkins-login");

test.use({ ignoreHTTPSErrors: true });

const env = {
  keycloakBaseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || ""),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME),
  superAdminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME),
  superAdminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD),
  keycloakAdminRealm: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_REALM),
  keycloakAdminCliClientId: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  biberFullName: decodeDotenvQuotedValue(process.env.BIBER_FULL_NAME),
  biberEmail: decodeDotenvQuotedValue(process.env.BIBER_EMAIL),
  administratorGroupPath: decodeDotenvQuotedValue(process.env.RBAC_ADMINISTRATOR_GROUP_PATH),
  developerGroupPath: decodeDotenvQuotedValue(process.env.RBAC_DEVELOPER_GROUP_PATH),
  viewerGroupPath: decodeDotenvQuotedValue(process.env.RBAC_VIEWER_GROUP_PATH),
  ldapGroupPrefix: decodeDotenvQuotedValue(process.env.RBAC_LDAP_GROUP_PREFIX),
  mcpCredentialOwner: decodeDotenvQuotedValue(process.env.MCP_CREDENTIAL_OWNER),
  mcpJenkinsRole: decodeDotenvQuotedValue(process.env.MCP_JENKINS_ROLE),
};

/**
 * Run `fn` with a fresh page logged in as the platform administrator.
 *
 * Args:
 *   browser: the Playwright browser, used for an isolated context.
 *   fn: async body receiving the administrator page.
 */
async function withAdministrator(browser, fn) {
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await ctx.newPage();
    await loginAsAdministrator(page);
    return await fn(page);
  } finally {
    await ctx.close().catch(() => {});
  }
}

/**
 * Return the role-strategy record of one global role as the administrator sees it.
 *
 * Args:
 *   page: a Playwright page logged in as the administrator.
 *   roleName: the global role name from templates/casc.yaml.j2.
 */
async function globalRole(page, roleName) {
  const response = await page.request.get(
    `${baseUrl}/manage/role-strategy/strategy/getRole?type=globalRoles&roleName=${encodeURIComponent(roleName)}`,
    { failOnStatusCode: false, timeout: resolveTimeout(30_000) },
  );
  expect(response.status(), `the role-strategy API must answer for the global role ${roleName}`).toBe(200);
  return response.json();
}

/**
 * Assert that Jenkins stored biber's full name and mail address from the
 * identity provider at his last login.
 *
 * Args:
 *   browser: the Playwright browser, used for an isolated administrator context.
 *   expectedFullName: the full name the identity provider holds, or null when only its presence is known.
 */
async function expectBiberProfileSynced(browser, expectedFullName) {
  await withAdministrator(browser, async (page) => {
    const response = await page.request.get(
      `${baseUrl}/user/${encodeURIComponent(env.biberUsername)}/api/json?depth=1`,
      { failOnStatusCode: false, timeout: resolveTimeout(30_000) },
    );
    expect(response.status(), "the administrator must read biber's Jenkins user record").toBe(200);
    const record = await response.json();
    if (expectedFullName === null) {
      expect(record.fullName, "Jenkins MUST take biber's full name from the directory").toBeTruthy();
    } else {
      expect(record.fullName, "Jenkins MUST take biber's full name from the identity provider").toBe(expectedFullName);
    }
    const addresses = (record.property || []).map((property) => property.address).filter(Boolean);
    expect(addresses, "Jenkins MUST take biber's mail address from the identity provider").toContain(env.biberEmail);
  });
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
  const adminOpts = { adminRealm: env.keycloakAdminRealm, adminClientId: env.keycloakAdminCliClientId };
  const adminCtx = await browser.newContext({ ignoreHTTPSErrors: true });
  let biberAdded = false;
  try {
    biberAdded = await keycloakAdmin.keycloakAdminAddUserToGroup(
      adminCtx.request,
      env.keycloakBaseUrl,
      env.realmName,
      groupPath,
      env.biberUsername,
      env.superAdminUsername,
      env.superAdminPassword,
      adminOpts,
    );
    return await fn();
  } finally {
    if (biberAdded) {
      await keycloakAdmin
        .keycloakRemoveUserFromGroupViaRest(
          adminCtx.request,
          env.keycloakBaseUrl,
          env.realmName,
          env.superAdminUsername,
          env.superAdminPassword,
          groupPath,
          env.biberUsername,
          adminOpts,
        )
        .catch((err) => console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`));
    }
    await adminCtx.close().catch(() => {});
  }
}

/**
 * Return the HTTP status Jenkins answers for a path in the page's session.
 *
 * Args:
 *   page: a Playwright page whose context carries the Jenkins session.
 *   path: the controller-relative path, starting with a slash.
 */
async function statusOf(page, path) {
  const response = await page.request.get(`${baseUrl}${path}`, {
    failOnStatusCode: false,
    maxRedirects: 0,
    timeout: resolveTimeout(30_000),
  });
  return response.status();
}

/**
 * Delete a job through the REST endpoint with the session's CSRF crumb,
 * tolerating a job that is already gone.
 *
 * Args:
 *   page: a Playwright page whose context carries a session allowed to delete the job.
 *   jobName: the job to remove.
 */
async function deleteJob(page, jobName) {
  const crumbResponse = await page.request.get(`${baseUrl}/crumbIssuer/api/json`, { failOnStatusCode: false });
  const headers = {};
  if (crumbResponse.ok()) {
    const crumb = await crumbResponse.json();
    headers[crumb.crumbRequestField] = crumb.crumb;
  }
  const response = await page.request.post(`${baseUrl}/job/${encodeURIComponent(jobName)}/doDelete`, {
    headers,
    failOnStatusCode: false,
    maxRedirects: 0,
  });
  if (response.status() >= 400 && response.status() !== 404) {
    throw new Error(`Deleting job ${jobName} answered ${response.status()}`);
  }
}

/**
 * Assert that an authenticated biber session without any Jenkins role
 * group can neither read the controller nor reach its management pages.
 *
 * Args:
 *   page: a Playwright page logged in as biber.
 */
async function expectBiberRefused(page) {
  const identity = await whoAmI(page);
  expect(identity.authenticated, `biber must hold a real Jenkins session (whoAmI: ${JSON.stringify(identity)})`).toBe(true);
  expect(
    await statusOf(page, "/"),
    "biber without a Jenkins role group MUST be refused the dashboard; a 200 means every realm user can read the controller",
  ).toBe(403);
  expect(
    await statusOf(page, "/manage/"),
    "biber without a Jenkins role group MUST NOT reach Manage Jenkins",
  ).toBe(403);
}

test("rbac: biber without a Jenkins role group is refused after OIDC login", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000)); // two Keycloak round-trips: biber, then the administrator for the profile read
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await ctx.newPage();
    await loginAs(page, env.biberUsername, env.biberPassword);
    await expectBiberRefused(page);
  } finally {
    await ctx.close().catch(() => {});
  }
  await expectBiberProfileSynced(browser, env.biberFullName);
});

test("biber: without a Jenkins role group, biber is refused after LDAP login", async ({ browser }) => {
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceDisabled("sso");
  test.setTimeout(resolveTimeout(120_000)); // biber login plus an administrator login for the profile read
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await ctx.newPage();
    await loginAs(page, env.biberUsername, env.biberPassword);
    await expectBiberRefused(page);
  } finally {
    await ctx.close().catch(() => {});
  }
  await expectBiberProfileSynced(browser, null);
});

test("administrator: the LDAP realm grants each Jenkins role to its directory group", async ({ browser }) => {
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceDisabled("sso");
  await withAdministrator(browser, async (page) => {
    for (const [jenkinsRole, rbacRole] of [["admin", "administrator"], ["developer", "developer"], ["viewer", "viewer"]]) {
      const role = await globalRole(page, jenkinsRole);
      expect(
        JSON.stringify(role.sids || []),
        `the ${jenkinsRole} role MUST be granted to the directory group ${env.ldapGroupPrefix}${rbacRole}`,
      ).toContain(`"${env.ldapGroupPrefix}${rbacRole}"`);
    }
  });
});

test("rbac: membership in the viewer group lets biber read Jenkins but not create jobs", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000)); // Keycloak round-trip plus the oic callback
  await withBiberInGroup(browser, env.viewerGroupPath, async () => {
    const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      const page = await ctx.newPage();
      await loginAs(page, env.biberUsername, env.biberPassword);
      const landing = await gotoOnion(page, `${baseUrl}/`, { waitUntil: "domcontentloaded" });
      expect(landing ? landing.status() : 0, "a viewer MUST read the Jenkins dashboard").toBeLessThan(400);
      await expect(page.locator("#root-action-UserAction").first()).toBeVisible({ timeout: resolveTimeout(60_000) });
      expect(await statusOf(page, "/view/all/newJob"), "a viewer MUST NOT reach the job creation page").toBe(403);
      expect(await statusOf(page, "/manage/"), "a viewer MUST NOT reach Manage Jenkins").toBe(403);
    } finally {
      await ctx.close().catch(() => {});
    }
  });
});

test("rbac: the MCP credential owner holds the Jenkins role its tool scope needs", async ({ browser }) => {
  skipUnlessServiceEnabled("mcp");
  test.setTimeout(resolveTimeout(120_000)); // administrator login plus two role-strategy reads
  await withAdministrator(browser, async (page) => {
    const role = await globalRole(page, env.mcpJenkinsRole);
    expect(
      JSON.stringify(role.sids || []),
      `the MCP credential owner ${env.mcpCredentialOwner} MUST hold the ${env.mcpJenkinsRole} role, or every MCP tool call is refused`,
    ).toContain(`"${env.mcpCredentialOwner}"`);
    const admin = await globalRole(page, "admin");
    expect(
      JSON.stringify(admin.sids || []),
      "the MCP credential owner MUST NOT administer Jenkins",
    ).not.toContain(`"${env.mcpCredentialOwner}"`);
  });
});

test("rbac: membership in the developer group lets biber create and build a job but not manage Jenkins", async ({
  browser,
}) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(300_000)); // Keycloak round-trip, job creation and one freestyle build on the built-in node
  const jobName = `infinito-rbac-developer-${Date.now()}`;
  await withBiberInGroup(browser, env.developerGroupPath, async () => {
    const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
    const page = await ctx.newPage();
    try {
      await loginAs(page, env.biberUsername, env.biberPassword);
      const identity = await whoAmI(page);
      expect(
        identity.authorities || [],
        `Jenkins MUST receive the developer group from the groups claim (whoAmI: ${JSON.stringify(identity)})`,
      ).toContain(env.developerGroupPath);

      await gotoOnion(page, `${baseUrl}/view/all/newJob`, { waitUntil: "domcontentloaded" });
      await page.locator("input#name").fill(jobName);
      const freestyle = page.locator("input[name='mode'][value='hudson.model.FreeStyleProject']");
      await page.locator("label").filter({ has: freestyle }).click();
      await expect(freestyle, "the freestyle project type must be the selected item type").toBeChecked();
      await page.locator("#ok-button").click({ timeout: resolveTimeout(30_000) });
      await expect
        .poll(() => page.url(), {
          timeout: resolveTimeout(60_000),
          message: "a developer MUST land on the configuration page of the job it created",
        })
        .toContain(`/job/${jobName}/configure`);
      await page.locator("button[name='Submit']").first().click({ timeout: resolveTimeout(30_000) });
      await expect
        .poll(() => page.url(), { timeout: resolveTimeout(60_000) })
        .not.toContain("/configure");

      await page
        .getByRole("link", { name: /build now/i })
        .or(page.getByRole("button", { name: /build now/i }))
        .first()
        .click({ timeout: resolveTimeout(30_000) });
      await expect
        .poll(
          async () => {
            const response = await page.request.get(
              `${baseUrl}/job/${encodeURIComponent(jobName)}/api/json?tree=lastCompletedBuild[number,result]`,
              { failOnStatusCode: false },
            );
            if (!response.ok()) return `HTTP ${response.status()}`;
            const build = (await response.json()).lastCompletedBuild;
            return build ? build.result : "no completed build";
          },
          {
            timeout: resolveTimeout(180_000),
            message: "the build a developer started MUST complete successfully",
          },
        )
        .toBe("SUCCESS");

      expect(
        await statusOf(page, "/manage/"),
        "a developer MUST NOT reach Manage Jenkins",
      ).toBe(403);
    } finally {
      await deleteJob(page, jobName).catch((err) => console.warn(`Cleanup of job ${jobName} failed: ${err}`));
      await ctx.close().catch(() => {});
    }
  });
});

test("rbac: membership in the administrator group lets biber manage Jenkins", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000)); // Keycloak round-trip plus the oic callback
  await withBiberInGroup(browser, env.administratorGroupPath, async () => {
    const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      const page = await ctx.newPage();
      await loginAs(page, env.biberUsername, env.biberPassword);
      const landing = await gotoOnion(page, `${baseUrl}/manage/`, { waitUntil: "domcontentloaded" });
      expect(
        landing ? landing.status() : 0,
        "a member of the administrator group MUST reach Manage Jenkins",
      ).toBeLessThan(400);
      await expect(page.locator("a[href$='configureSecurity'], a[href$='configureSecurity/']").first()).toBeVisible({
        timeout: resolveTimeout(60_000),
      });
    } finally {
      await ctx.close().catch(() => {});
    }
  });
});

test("rbac: the platform administrator reaches the security settings", async ({ page }) => {
  test.setTimeout(resolveTimeout(180_000)); // Keycloak round-trip plus the oic callback
  await loginAsAdministrator(page);
  const landing = await gotoOnion(page, `${baseUrl}/manage/configureSecurity/`, { waitUntil: "domcontentloaded" });
  expect(
    landing ? landing.status() : 0,
    "the platform administrator MUST reach the security settings",
  ).toBeLessThan(400);
  await expect(page.locator("form[name='config'], form[action*='configure']").first()).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
});
