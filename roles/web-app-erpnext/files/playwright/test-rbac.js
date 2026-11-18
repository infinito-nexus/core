const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { requireDotenvValue, withLdapAttributes, withLdapGroupMember } = require("./personas");

const rbacEnv = {
  biberEmail: requireDotenvValue(process.env.BIBER_EMAIL, "BIBER_EMAIL").toLowerCase(),
  biberLastname: requireDotenvValue(process.env.BIBER_LASTNAME, "BIBER_LASTNAME"),
  biberDn: requireDotenvValue(process.env.BIBER_LDAP_DN, "BIBER_LDAP_DN"),
  managerGroupDn: requireDotenvValue(process.env.LDAP_MANAGER_GROUP_DN, "LDAP_MANAGER_GROUP_DN"),
  phoneAttribute: requireDotenvValue(process.env.LDAP_PHONE_ATTRIBUTE, "LDAP_PHONE_ATTRIBUTE"),
  mobileAttribute: requireDotenvValue(process.env.LDAP_MOBILE_ATTRIBUTE, "LDAP_MOBILE_ATTRIBUTE"),
  rolesDn: requireDotenvValue(process.env.LDAP_ROLES_DN, "LDAP_ROLES_DN"),
  groupRoles: JSON.parse(requireDotenvValue(process.env.RBAC_GROUP_ROLES_JSON, "RBAC_GROUP_ROLES_JSON")),
};

const LDAP_LOGIN = "/api/method/frappe.integrations.doctype.ldap_settings.ldap_settings.login";

function mappedGroupDn(path) {
  const [, application, role] = path.replace(/^\/+|\/+$/g, "").split("/");
  return `cn=${application}-${role},${rbacEnv.rolesDn}`;
}

async function signInThroughDirectory(shared, page, browser, label) {
  if (shared.env.oidcEnabled) {
    await shared.signInViaErpnextOidc(page, shared.env.biberUsername, shared.env.biberPassword, "biber");
    await shared.erpnextLogout(page);
    return;
  }
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const response = await context.request.post(`${shared.env.erpnextBaseUrl}${LDAP_LOGIN}`, {
      form: { usr: shared.env.biberUsername, pwd: shared.env.biberPassword },
      timeout: resolveTimeout(60_000),
    });
    expect(response.status(), `${label} must sign in through LDAP: ${await response.text()}`).toBe(200);
    await context.request.get(`${shared.env.erpnextBaseUrl}/api/method/logout`).catch(() => {});
  } finally {
    await context.close().catch(() => {});
  }
}

async function withBreakGlassApi(shared, body) {
  const api = await shared.breakGlassApi();
  try {
    return await body(api);
  } finally {
    await api.dispose().catch(() => {});
  }
}

async function erpnextUser(request, shared, email) {
  const response = await request.get(`${shared.env.erpnextBaseUrl}/api/resource/User/${encodeURIComponent(email)}`, {
    timeout: resolveTimeout(60_000),
  });
  if (response.status() === 404) return null;
  expect(response.status(), `reading the ERPNext user ${email} must succeed`).toBe(200);
  return (await response.json()).data;
}

function roleNames(user) {
  return (user && user.roles ? user.roles : []).map((row) => row.role);
}

exports.register = function (shared) {
  test.describe.serial("erpnext RBAC", () => {
    require("./test-login-biber").register(shared);

    test("administrator: the deploy-time reconcile grants System Manager to the administrator group", async ({ page }) => {
      shared.skipUnlessServiceEnabled("sso");
      test.setTimeout(resolveTimeout(180_000)); // OIDC round-trip plus the break-glass API read

      await shared.signInViaErpnextOidc(page, shared.env.adminUsername, shared.env.adminPassword, "administrator");
      const logged = await page.request.get(`${shared.env.erpnextBaseUrl}/api/method/frappe.auth.get_logged_user`);
      expect(logged.status(), "the administrator must hold an ERPNext session after the OIDC sign-in").toBe(200);
      expect(((await logged.json()).message || "").toLowerCase()).toBe(shared.env.adminEmail.toLowerCase());
      await shared.erpnextLogout(page);

      await withBreakGlassApi(shared, async (request) => {
        const user = await erpnextUser(request, shared, shared.env.adminEmail);
        expect(roleNames(user), "members of the administrator group must hold System Manager").toContain("System Manager");
      });
    });

    test("biber: LDAP sign-in without an ERPNext role is refused", async ({ browser }) => {
      shared.skipUnlessServiceEnabled("ldap");
      shared.skipUnlessServiceDisabled("sso");
      test.setTimeout(resolveTimeout(120_000)); // directory bind through Frappe

      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const response = await context.request.post(`${shared.env.erpnextBaseUrl}${LDAP_LOGIN}`, {
          form: { usr: shared.env.biberUsername, pwd: shared.env.biberPassword },
          timeout: resolveTimeout(60_000),
        });
        expect(response.status(), "the LDAP search string admits only members of a declared role group").not.toBe(200);
      } finally {
        await context.close().catch(() => {});
      }
    });

    test("biber: LDAP sign-in with the manager group syncs the roles and the directory profile", async ({ browser }) => {
      shared.skipUnlessServiceEnabled("ldap");
      shared.skipUnlessServiceDisabled("sso");
      test.setTimeout(resolveTimeout(300_000)); // attribute and group writes to the directory, bind, API read and teardown

      const profile = { [rbacEnv.phoneAttribute]: "+49 30 1112223", [rbacEnv.mobileAttribute]: "+49 170 4445556" };
      await withLdapGroupMember(rbacEnv.managerGroupDn, rbacEnv.biberDn, () =>
        withLdapAttributes(rbacEnv.biberDn, profile, async () => {
          const context = await browser.newContext({ ignoreHTTPSErrors: true });
          try {
            const response = await context.request.post(`${shared.env.erpnextBaseUrl}${LDAP_LOGIN}`, {
              form: { usr: shared.env.biberUsername, pwd: shared.env.biberPassword },
              timeout: resolveTimeout(60_000),
            });
            expect(response.status(), `a manager-group member must sign in through LDAP: ${await response.text()}`).toBe(200);
            await context.request.get(`${shared.env.erpnextBaseUrl}/api/method/logout`).catch(() => {});
          } finally {
            await context.close().catch(() => {});
          }

          await withBreakGlassApi(shared, async (adminRequest) => {
            const user = await erpnextUser(adminRequest, shared, rbacEnv.biberEmail);
            expect(user, "the LDAP sign-in must create or update biber").toBeTruthy();
            expect(roleNames(user), "the manager group must grant Sales User").toContain("Sales User");
            expect(roleNames(user), "the manager group must not grant System Manager").not.toContain("System Manager");
            expect(user.last_name, "the directory surname must land in the last name").toBe(rbacEnv.biberLastname);
            expect(user.phone, `the directory ${rbacEnv.phoneAttribute} must land in the phone`).toBe("+49 30 1112223");
            expect(user.mobile_no, `the directory ${rbacEnv.mobileAttribute} must land in the mobile number`).toBe("+49 170 4445556");
          });
        }),
      );
    });

    test("biber: a sign-in in a group of services.erpnext.group_roles holds its mapped roles at once", async ({ page, browser }) => {
      shared.skipUnlessServiceEnabled("ldap");
      const mapped = Object.entries(rbacEnv.groupRoles);
      test.skip(mapped.length === 0, "the inventory maps no group in services.erpnext.group_roles");
      test.setTimeout(resolveTimeout(300_000));

      const [path, roles] = mapped[0];
      await withLdapGroupMember(mappedGroupDn(path), rbacEnv.biberDn, async () => {
        await signInThroughDirectory(shared, page, browser, `a member of ${path}`);

        await withBreakGlassApi(shared, async (adminRequest) => {
          const user = await erpnextUser(adminRequest, shared, rbacEnv.biberEmail);
          expect(user, `the sign-in must give the member of ${path} an account`).toBeTruthy();
          expect(user.enabled, `the account of the member of ${path} must be enabled`).toBe(1);
          for (const role of roles) {
            expect(roleNames(user), `${path} must grant ${role} at sign-in`).toContain(role);
          }
        });
      });
    });
  });
};
