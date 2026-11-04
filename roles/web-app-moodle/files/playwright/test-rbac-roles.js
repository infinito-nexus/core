const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue, gotoOnion, inAppLogout, withLdapGroupMember } = require("./personas");

const ldapGroupMemberAttribute = decodeDotenvQuotedValue(process.env.LDAP_GROUP_MEMBER_ATTRIBUTE || "");
const ldapRoleGroupDns = {
  manager: decodeDotenvQuotedValue(process.env.LDAP_MANAGER_GROUP_DN || ""),
  coursecreator: decodeDotenvQuotedValue(process.env.LDAP_COURSECREATOR_GROUP_DN || ""),
};
const biberDn = decodeDotenvQuotedValue(process.env.BIBER_LDAP_DN);

const ADMIN_SETTINGS_PATH = "/admin/settings.php?section=frontpagesettings";
const ADMIN_SETTINGS_FORM = "form#adminsettings";
const COURSE_CREATE_PATH = "/course/edit.php?category=1";
const COURSE_FULLNAME_FIELD = "input[name='fullname']";
const PERMISSION_DENIED = /permission|access denied|section error|berechtigung|zugriff verweigert/i;

async function logoutAndAssertSessionGone(shared, page) {
  await gotoOnion(page, `${shared.env.moodleBaseUrl}/my/`, { waitUntil: "domcontentloaded" });
  await inAppLogout(page);
  await gotoOnion(page, `${shared.env.moodleBaseUrl}${ADMIN_SETTINGS_PATH}`, { waitUntil: "domcontentloaded" });
  await expect(
    page.locator(ADMIN_SETTINGS_FORM),
    "after the logout click the site administration must re-engage the login",
  ).toHaveCount(0, { timeout: resolveTimeout(30_000) });
}

async function assertAdministratorHoldsSiteAdministration(shared, page) {
  expect(shared.env.rbacAdminUsername, "RBAC_ADMIN_USERNAME must be set").toBeTruthy();
  expect(shared.env.rbacAdminPassword, "RBAC_ADMIN_PASSWORD must be set").toBeTruthy();

  await shared.loginAsDirectoryUser(page, shared.env.rbacAdminUsername, shared.env.rbacAdminPassword);

  await gotoOnion(page, `${shared.env.moodleBaseUrl}${ADMIN_SETTINGS_PATH}`, { waitUntil: "domcontentloaded" });
  await expect(
    page.locator(ADMIN_SETTINGS_FORM),
    "a member of the web-app-moodle administrator group must reach a Site administration settings page after the reconcile listed it in $CFG->siteadmins",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });

  await logoutAndAssertSessionGone(shared, page);
}

async function assertBiberHoldsNoRole(shared, page) {
  await shared.loginAsDirectoryUser(page, shared.env.biberUsername, shared.env.biberPassword);

  await gotoOnion(page, `${shared.env.moodleBaseUrl}${ADMIN_SETTINGS_PATH}`, { waitUntil: "domcontentloaded" });
  await expect(page.locator("body")).toContainText(PERMISSION_DENIED, { timeout: resolveTimeout(60_000) });
  await expect(
    page.locator(ADMIN_SETTINGS_FORM),
    "biber holds no web-app-moodle role, so the reconcile must keep it out of $CFG->siteadmins",
  ).toHaveCount(0);

  await gotoOnion(page, `${shared.env.moodleBaseUrl}${COURSE_CREATE_PATH}`, { waitUntil: "domcontentloaded" });
  await expect(
    page.locator("body"),
    "biber holds neither the manager nor the coursecreator role, so creating a course must be refused",
  ).toContainText(PERMISSION_DENIED, { timeout: resolveTimeout(60_000) });
  await expect(page.locator(COURSE_FULLNAME_FIELD)).toHaveCount(0);

  await logoutAndAssertSessionGone(shared, page);
}

exports.register = function (shared) {
  test.describe("moodle RBAC reconcile", () => {
    test("administrator: the inventory administrator holds Moodle site administration", async ({ page }) => {
      skipUnlessServiceEnabled("sso");
      test.setTimeout(resolveTimeout(180_000));
      await assertAdministratorHoldsSiteAdministration(shared, page);
    });

    test("administrator: the inventory administrator holds Moodle site administration through the LDAP login", async ({ page }) => {
      skipUnlessServiceEnabled("ldap");
      skipUnlessServiceDisabled("sso");
      test.setTimeout(resolveTimeout(180_000));
      await assertAdministratorHoldsSiteAdministration(shared, page);
    });

    test("administrator: auth_ldap maps the manager and coursecreator role groups through their member attribute", async ({ page }) => {
      skipUnlessServiceEnabled("ldap");
      test.setTimeout(resolveTimeout(180_000));
      expect(ldapGroupMemberAttribute, "LDAP_GROUP_MEMBER_ATTRIBUTE must be set").toBeTruthy();

      await shared.loginAsDirectoryUser(page, shared.env.rbacAdminUsername, shared.env.rbacAdminPassword);

      await gotoOnion(page, `${shared.env.moodleBaseUrl}/admin/settings.php?section=authsettingldap`, { waitUntil: "domcontentloaded" });
      await expect(page.locator(ADMIN_SETTINGS_FORM)).toBeVisible({ timeout: resolveTimeout(60_000) });
      await expect(
        page.locator("[name='s_auth_ldap_memberattribute']"),
        "auth_ldap reads role membership off the group entry, so its member attribute must be the group's member attribute",
      ).toHaveValue(ldapGroupMemberAttribute);
      await expect(
        page.locator("[name='s_auth_ldap_memberattribute_isdn']"),
        "groupOfNames lists member DNs, so auth_ldap must compare the user's DN",
      ).toHaveValue("1");
      for (const [role, dn] of Object.entries(ldapRoleGroupDns)) {
        expect(dn, `the ${role} group DN must be rendered into the env`).toBeTruthy();
        await expect(
          page.locator(`[name='s_auth_ldap_${role}context']`),
          `auth_ldap must map Moodle's ${role} system role to the web-app-moodle ${role} RBAC group`,
        ).toHaveValue(dn);
      }

      await logoutAndAssertSessionGone(shared, page);
    });

    test("biber: an account without RBAC role holds neither site administration nor course creation", async ({ page }) => {
      skipUnlessServiceEnabled("sso");
      test.setTimeout(resolveTimeout(180_000));
      await assertBiberHoldsNoRole(shared, page);
    });

    test("biber: an account without RBAC role holds neither site administration nor course creation through the LDAP login", async ({ page }) => {
      skipUnlessServiceEnabled("ldap");
      skipUnlessServiceDisabled("sso");
      test.setTimeout(resolveTimeout(180_000));
      await assertBiberHoldsNoRole(shared, page);
    });

    for (const [role, groupDn] of Object.entries(ldapRoleGroupDns)) {
      test(`biber: membership in the ${role} role group grants course creation through auth_ldap at the next login`, async ({ page }) => {
        skipUnlessServiceEnabled("ldap");
        skipUnlessServiceDisabled("sso");
        test.setTimeout(resolveTimeout(240_000));

        await withLdapGroupMember(groupDn, biberDn, async () => {
          await shared.loginAsDirectoryUser(page, shared.env.biberUsername, shared.env.biberPassword);
          await gotoOnion(page, `${shared.env.moodleBaseUrl}${COURSE_CREATE_PATH}`, { waitUntil: "domcontentloaded" });
          await expect(
            page.locator(COURSE_FULLNAME_FIELD),
            `biber in ${groupDn} must hold the ${role} system role after the LDAP login and reach the course creation form`,
          ).toBeVisible({ timeout: resolveTimeout(60_000) });
          await logoutAndAssertSessionGone(shared, page);
        });

        await shared.loginAsDirectoryUser(page, shared.env.biberUsername, shared.env.biberPassword);
        await gotoOnion(page, `${shared.env.moodleBaseUrl}${COURSE_CREATE_PATH}`, { waitUntil: "domcontentloaded" });
        await expect(
          page.locator("body"),
          `leaving ${groupDn} must make auth_ldap unassign the ${role} system role at the next LDAP login`,
        ).toContainText(PERMISSION_DENIED, { timeout: resolveTimeout(60_000) });
        await expect(page.locator(COURSE_FULLNAME_FIELD)).toHaveCount(0);

        await logoutAndAssertSessionGone(shared, page);
      });
    }
  });
};
