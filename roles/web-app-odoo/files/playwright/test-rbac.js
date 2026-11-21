const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  awaitOnionHandoff,
  decodeDotenvQuotedValue,
  gotoOnion,
  keycloakAdminAddUserToGroup,
  keycloakAdminSetUserAttributes,
  keycloakRemoveUserFromGroupViaRest,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  withLdapAttributes,
  withLdapGroupMember,
} = require("./personas");
const { authenticatedContext, baseUrl, clickOdooSsoButton, loginMethods } = require("./_shared");

const env = {
  keycloakBaseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || ""),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME || ""),
  oidcIssuerUrl: decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL || "").replace(/\/$/, ""),
  superAdminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME || ""),
  superAdminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD || ""),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME || ""),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD || ""),
  biberEmail: decodeDotenvQuotedValue(process.env.BIBER_EMAIL || ""),
  database: decodeDotenvQuotedValue(process.env.ODOO_DB_NAME || ""),
  language: decodeDotenvQuotedValue(process.env.ODOO_LANGUAGE || ""),
  groups: {
    administrator: decodeDotenvQuotedValue(process.env.RBAC_GROUP_ADMINISTRATOR || ""),
    manager: decodeDotenvQuotedValue(process.env.RBAC_GROUP_MANAGER || ""),
    user: decodeDotenvQuotedValue(process.env.RBAC_GROUP_USER || ""),
    portal: decodeDotenvQuotedValue(process.env.RBAC_GROUP_PORTAL || ""),
  },
  directory: {
    biberDn: decodeDotenvQuotedValue(process.env.BIBER_LDAP_DN),
    userGroupDn: decodeDotenvQuotedValue(process.env.LDAP_USER_GROUP_DN),
    phoneAttribute: decodeDotenvQuotedValue(process.env.LDAP_PHONE_ATTRIBUTE),
    timezoneAttribute: decodeDotenvQuotedValue(process.env.LDAP_TIMEZONE_ATTRIBUTE),
  },
};

async function rpc(page, path, params) {
  const response = await page.request.post(`${baseUrl()}${path}`, {
    data: { jsonrpc: "2.0", method: "call", params },
    headers: { "Content-Type": "application/json" },
    timeout: resolveTimeout(60_000),
  });
  expect(response.ok(), `${path} must answer: ${response.status()}`).toBe(true);
  return response.json();
}

async function sessionInfo(page) {
  const body = await rpc(page, "/web/session/get_session_info", {});
  return body.result || {};
}

async function sessionUid(page) {
  return (await sessionInfo(page)).uid;
}

async function hasGroup(page, uid, xmlid) {
  const body = await rpc(page, "/web/dataset/call_kw/res.users/has_group", {
    model: "res.users",
    method: "has_group",
    args: [[uid], xmlid],
    kwargs: {},
  });
  expect(body.error, `has_group(${xmlid}) must not fail: ${JSON.stringify(body.error)}`).toBeFalsy();
  return body.result === true;
}

async function ownUser(page, uid, fields) {
  const body = await rpc(page, "/web/dataset/call_kw/res.users/read", {
    model: "res.users",
    method: "read",
    args: [[uid], fields],
    kwargs: {},
  });
  expect(body.error, `reading the own user must not fail: ${JSON.stringify(body.error)}`).toBeFalsy();
  return body.result[0];
}

async function ssoSignIn(page) {
  await page.context().clearCookies();
  await gotoOnion(page, `${baseUrl()}/web/login`);
  await clickOdooSsoButton(page);
  await awaitOnionHandoff(page, env.oidcIssuerUrl, async () => {
    await gotoOnion(page, `${baseUrl()}/web/login`);
    await clickOdooSsoButton(page);
  });
  await performKeycloakLoginForm(page, env.biberUsername, env.biberPassword);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "expected the OAuth callback to hand back to Odoo" })
    .toContain(baseUrl());
}

async function signOut(page) {
  const userMenu = page.locator("button.o_user_menu, .o_user_menu button").first();
  const shown = await userMenu
    .waitFor({ state: "visible", timeout: resolveTimeout(30_000) })
    .then(() => true)
    .catch(() => false);
  if (shown) {
    await userMenu.click({ timeout: resolveTimeout(30_000) });
    await page.locator('[data-menu="logout"]').first().click({ timeout: resolveTimeout(30_000) });
  } else {
    await page
      .locator(".dropdown:has(#o_logout) > .dropdown-toggle, li:has(#o_logout) > .dropdown-toggle")
      .first()
      .click({ timeout: resolveTimeout(15_000) })
      .catch(() => {});
    await page.locator("#o_logout").first().click({ timeout: resolveTimeout(15_000) }).catch(() => {});
  }
  await page.context().clearCookies();
}

async function withBiberIn(browser, groupPath, body) {
  const admin = await browser.newContext({ ignoreHTTPSErrors: true });
  let joined = false;
  try {
    joined = await keycloakAdminAddUserToGroup(
      admin.request,
      env.keycloakBaseUrl,
      env.realmName,
      groupPath,
      env.biberUsername,
      env.superAdminUsername,
      env.superAdminPassword,
    );
    await body(admin.request);
  } finally {
    if (joined) {
      await keycloakRemoveUserFromGroupViaRest(
        admin.request,
        env.keycloakBaseUrl,
        env.realmName,
        env.superAdminUsername,
        env.superAdminPassword,
        groupPath,
        env.biberUsername,
      ).catch((err) => console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`));
    }
    await admin.close().catch(() => {});
  }
}

async function ldapAuthenticate(page) {
  return rpc(page, "/web/session/authenticate", {
    db: env.database,
    login: env.biberUsername,
    password: env.biberPassword,
  });
}

function skipUnlessLdapLogin() {
  skipUnlessServiceEnabled("ldap");
  // nocheck: playwright-sso-ldap-gate -- gates on the ldap login method, which is off under SSO while the ldap service stays on
  test.skip(!loginMethods.ldap, "Odoo's own LDAP sign-in is off; LDAP accounts sign in through Keycloak's federation");
}

test.describe.serial("odoo RBAC and profile mapping", () => {
  test("biber: Keycloak sign-in without an Odoo role is refused", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(180_000)); // OAuth round-trip plus the refused callback

    await ssoSignIn(page);
    await expect
      .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "a user without a role must be sent back to the login page" })
      .toContain("oauth_error=");
    expect(await sessionUid(page), "a refused sign-in must not open an Odoo session").toBeFalsy();
    await page.context().clearCookies();
  });

  test("biber: the user group grants the internal user and the profile claims are written", async ({ page, browser }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(300_000)); // attribute update, group join, OAuth round-trip and teardown

    expect(env.language, "ODOO_LANGUAGE must be set").toBeTruthy();
    await withBiberIn(browser, env.groups.user, async (request) => {
      let previous = null;
      try {
        previous = await keycloakAdminSetUserAttributes(
          request,
          env.keycloakBaseUrl,
          env.realmName,
          env.biberUsername,
          { phoneNumber: "+49 30 7654321", zoneinfo: "Europe/Berlin", locale: env.language.replace("_", "-") },
          env.superAdminUsername,
          env.superAdminPassword,
        );
        await ssoSignIn(page);
        await expect(page.locator(".o_web_client, .o_main_navbar").first(), "a user-group member must reach the backend").toBeVisible({
          timeout: resolveTimeout(120_000),
        });
        const info = await sessionInfo(page);
        expect(info.uid, "the sign-in must open an Odoo session").toBeTruthy();
        expect(info.is_internal_user, "the user group must grant Internal User").toBe(true);
        expect(info.is_system, "the user group must not grant Settings").toBe(false);
        const user = await ownUser(page, info.uid, ["phone", "tz", "email", "lang"]);
        expect(user.phone, "the phone_number claim must land in the Odoo phone field").toBe("+49 30 7654321");
        expect(user.tz, "the zoneinfo claim must land in the Odoo time zone").toBe("Europe/Berlin");
        expect(user.lang, "the locale claim must select the platform language the deploy activated").toBe(env.language);
        expect((user.email || "").toLowerCase(), "the email claim must land in the Odoo email field").toBe(env.biberEmail.toLowerCase());
        await signOut(page);
      } finally {
        if (previous) {
          await keycloakAdminSetUserAttributes(
            request,
            env.keycloakBaseUrl,
            env.realmName,
            env.biberUsername,
            previous,
            env.superAdminUsername,
            env.superAdminPassword,
          ).catch((err) => console.warn(`Restoring biber's attributes failed: ${err}`));
        }
      }
    });
  });

  test("biber: the manager group grants the Sales administrator without Settings", async ({ page, browser }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(240_000)); // group join, OAuth round-trip and teardown

    await withBiberIn(browser, env.groups.manager, async () => {
      await ssoSignIn(page);
      await expect
        .poll(() => sessionUid(page), { timeout: resolveTimeout(60_000), message: "a manager-group member must get an Odoo session" })
        .toBeTruthy();
      const info = await sessionInfo(page);
      expect(info.is_internal_user, "the manager group must grant Internal User").toBe(true);
      expect(info.is_system, "the manager group must not grant Settings").toBe(false);
      expect(await hasGroup(page, info.uid, "sales_team.group_sale_manager"), "the manager group must grant the Sales administrator").toBe(true);
      await signOut(page);
    });
  });

  test("biber: the administrator group grants Settings", async ({ page, browser }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(240_000)); // group join, OAuth round-trip and teardown

    await withBiberIn(browser, env.groups.administrator, async () => {
      await ssoSignIn(page);
      await expect
        .poll(() => sessionUid(page), { timeout: resolveTimeout(60_000), message: "an administrator-group member must get an Odoo session" })
        .toBeTruthy();
      expect((await sessionInfo(page)).is_system, "the administrator group must grant Settings").toBe(true);
      await signOut(page);
    });
  });

  test("biber: the portal group grants the portal without backend access", async ({ page, browser }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(240_000)); // group join, OAuth round-trip and teardown

    await withBiberIn(browser, env.groups.portal, async () => {
      await ssoSignIn(page);
      await expect
        .poll(() => sessionUid(page), { timeout: resolveTimeout(60_000), message: "a portal-group member must get an Odoo session" })
        .toBeTruthy();
      expect((await sessionInfo(page)).is_internal_user, "the portal group must not grant Internal User").toBe(false);
      await signOut(page);
    });
  });

  test("administrator: the self-signup template is a portal user", async ({ browser }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(180_000)); // administrator OAuth round-trip

    const { context, page } = await authenticatedContext(browser);
    try {
      const body = await rpc(page, "/web/dataset/call_kw/res.users/search_read", {
        model: "res.users",
        method: "search_read",
        args: [[["login", "=", "_oauth_template"]], ["share"]],
        kwargs: { context: { active_test: false } },
      });
      expect(body.error, `reading the signup template must not fail: ${JSON.stringify(body.error)}`).toBeFalsy();
      expect(body.result, "tasks/05_oidc.yml must provision the _oauth_template user").toHaveLength(1);
      expect(body.result[0].share, "a self-signup copied from the template must not become an internal user").toBe(true);
    } finally {
      await context.close().catch(() => {});
    }
  });

  test("biber: LDAP sign-in without an Odoo role is refused", async ({ page }) => {
    skipUnlessLdapLogin();
    test.setTimeout(resolveTimeout(120_000)); // directory bind through Odoo

    const body = await ldapAuthenticate(page);
    expect(
      Boolean(body.error) || !(body.result && body.result.uid),
      `a directory user without a role must not authenticate: ${JSON.stringify(body.result || {})}`,
    ).toBe(true);
    await page.context().clearCookies();
  });

  test("biber: LDAP sign-in with the user group maps the directory mail, phone and time zone", async ({ page }) => {
    skipUnlessLdapLogin();
    test.setTimeout(resolveTimeout(240_000)); // directory group join and attribute write, bind and teardown

    const { directory } = env;
    await withLdapGroupMember(directory.userGroupDn, directory.biberDn, () =>
      withLdapAttributes(
        directory.biberDn,
        { [directory.phoneAttribute]: "+49 40 1234567", [directory.timezoneAttribute]: "Europe/Vienna" },
        async () => {
          const body = await ldapAuthenticate(page);
          expect(body.error, `a user-group member must authenticate through the directory: ${JSON.stringify(body.error)}`).toBeFalsy();
          const uid = body.result.uid;
          expect(uid, "the directory sign-in must open an Odoo session").toBeTruthy();
          expect(await hasGroup(page, uid, "base.group_user"), "the user group must grant Internal User").toBe(true);
          const user = await ownUser(page, uid, ["email", "phone", "tz"]);
          expect((user.email || "").toLowerCase(), "the directory mail must land in the Odoo email field").toBe(env.biberEmail.toLowerCase());
          expect(user.phone, `the directory ${directory.phoneAttribute} must land in the Odoo phone field`).toBe("+49 40 1234567");
          expect(user.tz, "the directory time zone must land in the Odoo time zone").toBe("Europe/Vienna");
          await page.context().clearCookies();
        },
      ),
    );
  });
});

module.exports = { env, withBiberIn };
