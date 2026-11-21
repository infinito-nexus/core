const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, withLdapGroupMember } = require("./personas");
const { skipUnlessServiceDisabled } = require("./service-gating");

const directory = {
  biberDn: decodeDotenvQuotedValue(process.env.BIBER_LDAP_DN),
  userGroupDn: decodeDotenvQuotedValue(process.env.LDAP_USER_GROUP_DN),
};

const KEYCLOAK_LOCALE_ATTRIBUTE = "locale";
const KEYCLOAK_ZONEINFO_ATTRIBUTE = "zoneinfo";
const PROFILE_LANGUAGE = "de";
const PROFILE_TIMEZONE = "Europe/Berlin";

function skipUnlessOidcRbac(shared) {
  shared.skipUnlessServiceEnabled("sso");
  // nocheck: playwright-sso-ldap-gate -- SSO_FLAVOR picks the taiga-oidc backend inside the canonical sso gate above; the flavor is no service flag
  test.skip(!shared.env.taigaOidcEnabled, "SSO_FLAVOR is not oidc; the taiga-oidc backend owns the group gate");
  // nocheck: playwright-sso-ldap-gate -- TAIGA_OIDC_PLUGIN_RBAC is a capability flag of the pinned taiga-oidc ref, no service flag
  test.skip(
    !shared.env.pluginRbac,
    "TAIGA_OIDC_PLUGIN_RBAC=false; the pinned taiga-oidc ref does not gate or map the groups claim yet"
  );
}

async function signInAsBiber(shared, page) {
  return shared.loginToTaigaAs(page, shared.env.biberUsername, shared.env.biberPassword);
}

async function seesAdminFieldsOf(shared, request, authToken, otherUsername) {
  const path = `users/by_username?username=${encodeURIComponent(otherUsername)}`;
  const response = await request.get(`${shared.getTaigaUrls().expectedTaigaBaseUrl}/api/v1/${path}`, {
    headers: { Authorization: `Bearer ${authToken}` },
    timeout: resolveTimeout(30_000),
  });
  expect(response.ok(), `Taiga API /api/v1/${path} answered ${response.status()}`).toBe(true);
  return Object.prototype.hasOwnProperty.call(await response.json(), "email");
}

async function provisionBiberAccount(shared, browser) {
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await ctx.newPage();
    const session = await signInAsBiber(shared, page);
    await shared.logoutFromTaiga(page, session);
  } finally {
    await ctx.close().catch(() => {});
  }
}

exports.register = function (shared) {
  test("biber: oidc login without a taiga role group is refused", async ({ page }) => {
    skipUnlessOidcRbac(shared);
    test.setTimeout(resolveTimeout(180_000));

    await shared.expectTaigaOidcLoginRefused(page, shared.env.biberUsername, shared.env.biberPassword);
  });

  test("biber: administrator role group grants taiga superuser and leaving it revokes superuser", async ({
    browser,
    page,
  }) => {
    skipUnlessOidcRbac(shared);
    test.setTimeout(resolveTimeout(420_000));

    await shared.withBiberInGroup(browser, shared.env.adminGroupPath, async () => {
      const session = await signInAsBiber(shared, page);
      expect(
        await shared.isTaigaSuperuser(page, shared.env.adminUsername),
        `${shared.env.biberUsername} in ${shared.env.adminGroupPath} MUST read another account's admin fields`
      ).toBe(true);
      await shared.logoutFromTaiga(page, session);
    });

    await page.context().clearCookies();
    await shared.withBiberInGroup(browser, shared.env.userGroupPath, async () => {
      const session = await signInAsBiber(shared, page);
      expect(
        await shared.isTaigaSuperuser(page, shared.env.adminUsername),
        `Leaving ${shared.env.adminGroupPath} MUST revoke Taiga superuser on the next login`
      ).toBe(false);
      await shared.logoutFromTaiga(page, session);
    });
  });

  test("biber: user role group admits oidc login without taiga superuser", async ({ browser, page }) => {
    skipUnlessOidcRbac(shared);
    test.setTimeout(resolveTimeout(240_000));

    await shared.withBiberInGroup(browser, shared.env.userGroupPath, async () => {
      const session = await signInAsBiber(shared, page);
      expect(
        await shared.isTaigaSuperuser(page, shared.env.adminUsername),
        `${shared.env.biberUsername} in ${shared.env.userGroupPath} only MUST NOT hold Taiga superuser rights`
      ).toBe(false);
      await shared.logoutFromTaiga(page, session);
    });
  });

  test("biber: oidc login syncs username, full name, language and timezone", async ({ browser, page }) => {
    skipUnlessOidcRbac(shared);
    test.setTimeout(resolveTimeout(240_000));

    await shared.withBiberInGroup(browser, shared.env.userGroupPath, async () => {
      await shared.withBiberAttributes(
        browser,
        { [KEYCLOAK_LOCALE_ATTRIBUTE]: PROFILE_LANGUAGE, [KEYCLOAK_ZONEINFO_ATTRIBUTE]: PROFILE_TIMEZONE },
        async () => {
          const session = await signInAsBiber(shared, page);
          const me = await shared.taigaApiGet(page, "users/me");
          expect(me.username, "Taiga username MUST come from the configured username claim").toBe(
            shared.env.biberUsername
          );
          expect(me.full_name, "Taiga full name MUST follow the name claim").toBe(shared.env.biberFullName);
          expect(me.lang, "Taiga language MUST follow the locale claim").toBe(PROFILE_LANGUAGE);
          expect(me.timezone, "Taiga timezone MUST follow the zoneinfo claim").toBe(PROFILE_TIMEZONE);
          await shared.logoutFromTaiga(page, session);
        }
      );
    });
  });

  test("administrator: bootstrap superuser keeps taiga superuser outside the administrator role group", async ({
    browser,
    page,
  }) => {
    skipUnlessOidcRbac(shared);
    test.setTimeout(resolveTimeout(480_000));

    await shared.withBiberInGroup(browser, shared.env.userGroupPath, () => provisionBiberAccount(shared, browser));
    await shared.withUserInGroup(browser, shared.env.adminUsername, shared.env.userGroupPath, () =>
      shared.withUserOutOfGroup(browser, shared.env.adminUsername, shared.env.adminGroupPath, async () => {
        const session = await shared.loginToTaigaAs(page, shared.env.adminUsername, shared.env.adminPassword);
        expect(
          await shared.isTaigaSuperuser(page, shared.env.biberUsername),
          "The bootstrap superuser MUST NOT be demoted by the groups claim"
        ).toBe(true);
        await shared.logoutFromTaiga(page, session);
      })
    );
  });

  test("biber: ldap login without a taiga role group is refused", async ({ page }) => {
    shared.skipUnlessServiceEnabled("ldap");
    skipUnlessServiceDisabled("sso");
    test.setTimeout(resolveTimeout(180_000));

    await shared.expectTaigaNativeLoginRefused(page, shared.env.biberUsername, shared.env.biberPassword);
  });

  test("biber: ldap backend refuses biber without a role group and admits it with the user group", async ({
    request,
  }) => {
    shared.skipUnlessServiceEnabled("ldap");
    skipUnlessServiceDisabled("sso");
    test.setTimeout(resolveTimeout(180_000));

    const refused = await shared.taigaLdapLogin(request, shared.env.biberUsername, shared.env.biberPassword);
    expect(refused.status, "The LDAP backend MUST refuse biber without a Taiga role group").not.toBe(200);
    expect(refused.authToken, "A refused LDAP login MUST NOT carry a Taiga auth token").toBeNull();

    await withLdapGroupMember(directory.userGroupDn, directory.biberDn, async () => {
      const admitted = await shared.taigaLdapLogin(request, shared.env.biberUsername, shared.env.biberPassword);
      expect(admitted.status, `The LDAP backend MUST admit biber in ${directory.userGroupDn}`).toBe(200);
      expect(admitted.authToken, "An admitted LDAP login MUST carry a Taiga auth token").toBeTruthy();
    });
  });

  test("administrator: ldap login of the administrator role member holds taiga superuser and biber in the user group does not", async ({
    request,
  }) => {
    shared.skipUnlessServiceEnabled("ldap");
    skipUnlessServiceDisabled("sso");
    test.setTimeout(resolveTimeout(180_000)); // two LDAP logins around one directory group change and its teardown

    await withLdapGroupMember(directory.userGroupDn, directory.biberDn, async () => {
      const biber = await shared.taigaLdapLogin(request, shared.env.biberUsername, shared.env.biberPassword);
      expect(biber.authToken, `The LDAP backend MUST admit biber in ${directory.userGroupDn}`).toBeTruthy();
      const administrator = await shared.taigaLdapLogin(request, shared.env.adminUsername, shared.env.adminPassword);
      expect(administrator.authToken, "The LDAP backend MUST admit the administrator role member").toBeTruthy();

      expect(
        await seesAdminFieldsOf(shared, request, administrator.authToken, shared.env.biberUsername),
        `${shared.env.adminUsername} MUST hold Taiga superuser rights after the deploy-time reconcile`
      ).toBe(true);
      expect(
        await seesAdminFieldsOf(shared, request, biber.authToken, shared.env.adminUsername),
        `${shared.env.biberUsername} outside ${shared.env.adminGroupPath} MUST NOT hold Taiga superuser rights`
      ).toBe(false);
    });
  });
};
