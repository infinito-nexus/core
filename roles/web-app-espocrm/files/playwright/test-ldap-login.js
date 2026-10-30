const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { gotoOnion, inAppLogout, normalizeBaseUrl, requireDotenvValue, withLdapGroupMember } = require("./personas");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");
const { awaitSession, espoApi } = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const biberUsername = requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME");
const biberPassword = requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD");
const biberDn = requireDotenvValue(process.env.BIBER_LDAP_DN, "BIBER_LDAP_DN");
const userGroupDn = requireDotenvValue(process.env.LDAP_USER_GROUP_DN, "LDAP_USER_GROUP_DN");
const userTeam = requireDotenvValue(process.env.ESPOCRM_TEAM_USER, "ESPOCRM_TEAM_USER");

/**
 * Args:
 *   page: a page without an EspoCRM session.
 *   username: the directory account to submit at EspoCRM's own form.
 *   password: the directory password of that account.
 *   admission: why ldapUserLoginFilter admits the account, shown when no session appears.
 */
async function signInThroughForm(page, username, password, admission) {
  await page.context().clearCookies();
  await gotoOnion(page, `${appBaseUrl}/`);

  const passwordField = page.locator("#field-password");
  await expect(
    passwordField,
    "with LDAP as authenticationMethod EspoCRM must render its own sign-in form",
  ).toBeEditable({ timeout: resolveTimeout(60_000) });
  await page.locator("#field-userName").fill(username);
  await passwordField.fill(password);
  await page.locator("#btn-login").click({ timeout: resolveTimeout(30_000) });

  await awaitSession(page, resolveTimeout(60_000), admission);
  await expect(page.locator("#navbar .navbar")).toBeVisible({ timeout: resolveTimeout(60_000) });
}

/**
 * Args:
 *   page: a page that shows the EspoCRM application of a signed-in account.
 */
async function signOut(page) {
  await inAppLogout(page);
  await expect(
    page.locator("#field-userName"),
    "after sign-out EspoCRM must offer its sign-in form again",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
}

test("administrator: LDAP sign-in at the EspoCRM form → administration panel → sign-out", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceDisabled("sso");

  await signInThroughForm(
    page,
    adminUsername,
    adminPassword,
    "ldapUserLoginFilter admits the administrator role group, so the directory bind must mint an EspoCRM session",
  );

  const me = await espoApi(page, "GET", "App/user");
  expect(me.status, `App/user must answer for the LDAP session: ${me.error}`).toBe(200);
  expect(me.json.user.userName, "the session must belong to the directory account of the administrator").toBe(adminUsername);
  expect(me.json.user.type, "the platform administrator must keep its EspoCRM administrator type").toBe("admin");

  await gotoOnion(page, `${appBaseUrl}/#Admin`);
  await expect(
    page.locator("#main .admin-tables-container table.table-admin-panel").first(),
    "the administration panel renders only for an EspoCRM administrator",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });

  await signOut(page);
});

test("biber: user role group in the directory → LDAP sign-in at the EspoCRM form → Users team without administration → sign-out", async ({
  page,
}) => {
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceDisabled("sso");

  await withLdapGroupMember(userGroupDn, biberDn, async () => {
    await signInThroughForm(
      page,
      biberUsername,
      biberPassword,
      `ldapUserLoginFilter admits the members of ${userGroupDn}, so the directory bind must mint an EspoCRM session`,
    );

    const me = await espoApi(page, "GET", "App/user");
    expect(me.status, `App/user must answer for the LDAP session: ${me.error}`).toBe(200);
    expect(me.json.user.userName, "the session must belong to the directory account of biber").toBe(biberUsername);
    expect(me.json.user.type, "a member of the user role group alone must be a regular EspoCRM user").toBe("regular");
    expect(me.json.user.teamsNames, "App/user must list the teams of the LDAP session").toBeTruthy();
    expect(
      Object.values(me.json.user.teamsNames),
      "the LDAP sign-in hook must grant the team of the user role group in this session",
    ).toContain(userTeam);

    await gotoOnion(page, `${appBaseUrl}/#Admin`);
    await expect(
      page.getByRole("heading", { level: 1, name: "403", exact: true }),
      "EspoCRM must answer the administration route of a regular user with its access-denied page",
    ).toBeVisible({ timeout: resolveTimeout(30_000) });
    await expect(
      page.locator("#main .admin-tables-container table.table-admin-panel"),
      "the administration panel renders only for an EspoCRM administrator",
    ).toHaveCount(0);

    await gotoOnion(page, `${appBaseUrl}/`);
    await expect(page.locator("#navbar .navbar")).toBeVisible({ timeout: resolveTimeout(60_000) });
    await signOut(page);
  });
});
