const { test, expect } = require("@playwright/test");

const {
  apiGetOnion,
  decodeDotenvJsonList,
  decodeDotenvQuotedValue,
  gotoOnion,
  keycloakAdminAddUserToGroup,
  keycloakAdminCreateUser,
  keycloakAdminDeleteUser,
  keycloakAdminToken,
  keycloakRemoveUserFromGroupViaRest,
  normalizeBaseUrl,
  requireDotenvValue,
  withLdapAttributes,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const { signInAs } = require("./sign-in");

const env = {
  discourseBaseUrl: normalizeBaseUrl(process.env.DISCOURSE_BASE_URL || ""),
  keycloakBaseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || ""),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME),
  superAdminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME),
  superAdminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  moderatorGroup: decodeDotenvQuotedValue(process.env.DISCOURSE_RBAC_MODERATOR_GROUP),
  administrators: decodeDotenvJsonList(process.env.DISCOURSE_RBAC_ADMINISTRATORS_JSON, "DISCOURSE_RBAC_ADMINISTRATORS_JSON"),
  moderators: decodeDotenvJsonList(process.env.DISCOURSE_RBAC_MODERATORS_JSON, "DISCOURSE_RBAC_MODERATORS_JSON"),
};

async function getJson(page, path, label) {
  const response = await apiGetOnion(page.request, `${env.discourseBaseUrl}${path}`, {
    headers: { Accept: "application/json" },
    timeout: resolveTimeout(30_000),
  });
  expect(response.status(), `expected ${path} to answer ${label}`).toBe(200);
  return response.json();
}

async function currentUser(page) {
  return (await getJson(page, "/session/current.json", "for a signed-in session")).current_user;
}

async function adminPanelStatus(page) {
  const response = await gotoOnion(page, `${env.discourseBaseUrl}/admin`, { waitUntil: "domcontentloaded" });
  return response ? response.status() : 0;
}

/**
 * Args:
 *   request: an APIRequestContext.
 *   buildFields: receives biber's Keycloak user representation and returns the top-level fields
 *     (`firstName`, `email`, `emailVerified`, ...) to write onto it.
 * Returns the values those fields carried before the write.
 */
async function keycloakUpdateBiber(request, buildFields) {
  const accessToken = await keycloakAdminToken(
    request,
    env.keycloakBaseUrl,
    env.superAdminUsername,
    env.superAdminPassword,
  );
  const headers = { Authorization: `Bearer ${accessToken}` };
  const usersUrl = `${env.keycloakBaseUrl}/admin/realms/${encodeURIComponent(env.realmName)}/users`;
  const lookup = await request.get(`${usersUrl}?username=${encodeURIComponent(env.biberUsername)}&exact=true`, {
    headers,
    timeout: resolveTimeout(30_000),
  });
  if (!lookup.ok()) {
    throw new Error(`Keycloak user lookup failed: ${lookup.status()} ${await lookup.text()}`);
  }
  const match = (await lookup.json()).find((user) => user.username === env.biberUsername);
  if (!match) {
    throw new Error(`Keycloak user "${env.biberUsername}" not found`);
  }
  const userUrl = `${usersUrl}/${match.id}`;
  const read = await request.get(userUrl, { headers, timeout: resolveTimeout(30_000) });
  if (!read.ok()) {
    throw new Error(`Keycloak user read failed: ${read.status()} ${await read.text()}`);
  }
  const user = await read.json();
  const fields = buildFields(user);
  const previous = Object.fromEntries(Object.keys(fields).map((key) => [key, user[key]]));
  const write = await request.put(userUrl, {
    headers: { ...headers, "Content-Type": "application/json" },
    data: { ...user, ...fields },
    timeout: resolveTimeout(30_000),
  });
  if (!write.ok()) {
    throw new Error(`Keycloak user update failed: ${write.status()} ${await write.text()}`);
  }
  return previous;
}

async function discourseAdminCall(page, method, path, body) {
  return page.evaluate(
    async ({ method, path, body }) => {
      const { csrf } = await (await fetch("/session/csrf.json")).json();
      const response = await fetch(path, {
        method,
        headers: { "X-CSRF-Token": csrf, "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
        body: body ? JSON.stringify(body) : undefined,
      });
      return { status: response.status, text: await response.text() };
    },
    { method, path, body },
  );
}

/**
 * Run `body` while the directory entry of `username` holds the mailbox address the RBAC sync timer gives a user created at runtime.
 *
 * Args:
 *   username: login of a user Keycloak wrote into the directory.
 *   body: async function executed while the address holds.
 *
 * Returns:
 *   the value `body` resolves to.
 */
async function withMailbox(username, body) {
  const dn = requireDotenvValue(process.env.LDAP_USER_DN_TEMPLATE, "LDAP_USER_DN_TEMPLATE").replace("<uid>", username);
  const attribute = requireDotenvValue(process.env.LDAP_MAIL_ATTRIBUTE, "LDAP_MAIL_ATTRIBUTE");
  const address = `${username}@${requireDotenvValue(process.env.DOMAIN_PRIMARY, "DOMAIN_PRIMARY")}`;
  return withLdapAttributes(dn, { [attribute]: address }, body);
}

async function withSignedIn(browser, username, password, body) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await context.newPage();
    await signInAs(page, username, password);
    return await body(page);
  } finally {
    await context.clearCookies().catch(() => {});
    await context.close().catch(() => {});
  }
}

exports.register = function () {
  test("administrator: the administrator role group carries the Discourse admin flag", async ({ page }) => {
    test.setTimeout(resolveTimeout(180_000));
    try {
      await signInAs(page, env.adminUsername, env.adminPassword);
      const user = await currentUser(page);
      expect(user.admin, `expected ${env.adminUsername} to hold the Discourse admin flag`).toBe(true);
      expect(await adminPanelStatus(page), "expected the admin panel to open for the administrator").toBe(200);
    } finally {
      await page.context().clearCookies().catch(() => {});
    }
  });

  test("administrator: every Discourse staff flag belongs to a member of the matching role group", async ({ page }) => {
    test.setTimeout(resolveTimeout(180_000));
    try {
      await signInAs(page, env.adminUsername, env.adminPassword);
      const staff = await getJson(page, "/admin/users/list/staff.json", "with the staff list");
      expect(Array.isArray(staff), "expected the staff list to be an array").toBe(true);
      expect(
        staff.some((user) => user.username.toLowerCase() === env.adminUsername.toLowerCase() && user.admin),
        `expected ${env.adminUsername} among the Discourse admins`,
      ).toBe(true);
      for (const user of staff) {
        const username = user.username.toLowerCase();
        if (user.admin) {
          expect(env.administrators, `expected admin ${user.username} to be a member of the administrator role group`).toContain(username);
        }
        if (user.moderator) {
          expect(env.moderators, `expected moderator ${user.username} to be a member of the moderator role group`).toContain(username);
        }
      }
      expect(
        staff.map((user) => user.username.toLowerCase()),
        "expected biber, who holds no role group, to carry no staff flag",
      ).not.toContain(env.biberUsername.toLowerCase());
    } finally {
      await page.context().clearCookies().catch(() => {});
    }
  });

  test("biber: no role group leaves biber without any Discourse staff flag", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(180_000));
    try {
      await signInAs(page, env.biberUsername, env.biberPassword);
      const user = await currentUser(page);
      expect(user.admin, `expected ${env.biberUsername} to hold no Discourse admin flag`).toBe(false);
      expect(user.moderator, `expected ${env.biberUsername} to hold no Discourse moderator flag`).toBe(false);
      expect(await adminPanelStatus(page), "expected the admin panel to stay closed for biber").toBe(404);
    } finally {
      await page.context().clearCookies().catch(() => {});
    }
  });

  test("biber: the Keycloak groups claim reaches Discourse as an associated group", async ({ browser }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(300_000));
    expect(env.moderatorGroup, "DISCOURSE_RBAC_MODERATOR_GROUP must be set").toBeTruthy();
    const requestContext = await browser.newContext({ ignoreHTTPSErrors: true });
    let joined = false;
    try {
      joined = await keycloakAdminAddUserToGroup(
        requestContext.request,
        env.keycloakBaseUrl,
        env.realmName,
        env.moderatorGroup,
        env.biberUsername,
        env.superAdminUsername,
        env.superAdminPassword,
      );
      await withSignedIn(browser, env.biberUsername, env.biberPassword, async () => {});
      const { associated_groups: associatedGroups } = await withSignedIn(
        browser,
        env.adminUsername,
        env.adminPassword,
        (page) => getJson(page, "/associated_groups.json", "with the associated groups"),
      );
      expect(
        associatedGroups.map((group) => `${group.provider_name}:${group.name}`),
        `expected biber's login to register ${env.moderatorGroup} from the groups claim`,
      ).toContain(`oidc:${env.moderatorGroup}`);
    } finally {
      if (joined) {
        await keycloakRemoveUserFromGroupViaRest(
          requestContext.request,
          env.keycloakBaseUrl,
          env.realmName,
          env.superAdminUsername,
          env.superAdminPassword,
          env.moderatorGroup,
          env.biberUsername,
        ).catch((err) => console.warn(`Removing biber from ${env.moderatorGroup} failed: ${err}`));
      }
      await requestContext.close().catch(() => {});
    }
  });

  test("throwaway: a Discourse username renamed by staff survives the next OIDC login", async ({ browser }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(360_000));
    expect(env.superAdminUsername, "SUPER_ADMIN_USERNAME must be set").toBeTruthy();
    expect(env.superAdminPassword, "SUPER_ADMIN_PASSWORD must be set").toBeTruthy();
    const marker = Date.now().toString(36);
    const throwaway = {
      username: `rename${marker}`,
      email: `rename${marker}@${new URL(env.discourseBaseUrl).hostname}`,
      firstName: "Rename",
      lastName: `Probe ${marker}`,
      password: `Probe-${marker}-Pw1!`,
    };
    const renamed = `renamed${marker}`;
    const mailbox = requireDotenvValue(process.env.KEYCLOAK_EMAIL_POLICY, "KEYCLOAK_EMAIL_POLICY") === "mailbox";
    const adminCtx = await browser.newContext({ ignoreHTTPSErrors: true });
    let keycloakId = null;
    let discourseId = null;
    try {
      keycloakId = await keycloakAdminCreateUser(
        adminCtx.request,
        env.keycloakBaseUrl,
        env.realmName,
        throwaway,
        env.superAdminUsername,
        env.superAdminPassword,
      );
      const renameSurvivesLogin = async () => {
        const first = await withSignedIn(browser, throwaway.username, throwaway.password, currentUser);
        expect(first.username.toLowerCase(), "the first login must create the Discourse account from the username claim").toBe(
          throwaway.username,
        );
        discourseId = first.id;

        await withSignedIn(browser, env.adminUsername, env.adminPassword, async (page) => {
          const result = await discourseAdminCall(page, "PUT", `/u/${encodeURIComponent(first.username)}/preferences/username.json`, {
            new_username: renamed,
          });
          expect(result.status, `staff must be able to rename the account: ${result.text.slice(0, 200)}`).toBe(200);
        });

        const second = await withSignedIn(browser, throwaway.username, throwaway.password, currentUser);
        expect(second.id, "the second login must reach the same Discourse account").toBe(discourseId);
        expect(
          second.username.toLowerCase(),
          "auth_overrides_username=false: the next login must keep the Discourse username instead of resetting it to the claim",
        ).toBe(renamed);
      };
      if (mailbox) {
        await withMailbox(throwaway.username, renameSurvivesLogin);
      } else {
        await renameSurvivesLogin();
      }
    } finally {
      if (discourseId) {
        await withSignedIn(browser, env.adminUsername, env.adminPassword, (page) =>
          discourseAdminCall(page, "DELETE", `/admin/users/${discourseId}.json`, { delete_posts: true }),
        ).catch((err) => console.warn(`Deleting the throwaway Discourse account failed: ${err}`));
      }
      if (keycloakId) {
        await keycloakAdminDeleteUser(
          adminCtx.request,
          env.keycloakBaseUrl,
          env.realmName,
          keycloakId,
          env.superAdminUsername,
          env.superAdminPassword,
        ).catch((err) => console.warn(`Deleting the throwaway Keycloak user failed: ${err}`));
      }
      await adminCtx.close().catch(() => {});
    }
  });

  test("biber: the Keycloak given name and email replace the Discourse ones on the next login", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(240_000));
    const marker = `biber${Date.now().toString(36)}`;
    const mailbox = requireDotenvValue(process.env.KEYCLOAK_EMAIL_POLICY, "KEYCLOAK_EMAIL_POLICY") === "mailbox";
    let markerEmail = "";
    const previous = await keycloakUpdateBiber(page.request, (user) => {
      const domain = mailbox ? new URL(env.discourseBaseUrl).hostname : String(user.email || "").split("@")[1];
      if (!domain) {
        throw new Error(`Keycloak user "${env.biberUsername}" carries no email to derive a marker address from`);
      }
      markerEmail = `${marker}@${domain}`.toLowerCase();
      return { firstName: marker, email: markerEmail, emailVerified: true };
    });
    const claimedEmail = mailbox ? requireDotenvValue(process.env.BIBER_EMAIL, "BIBER_EMAIL").toLowerCase() : markerEmail;
    try {
      await signInAs(page, env.biberUsername, env.biberPassword);
      const user = await currentUser(page);
      expect(user.name, "expected the Discourse name to follow the Keycloak given name").toContain(marker);
      const emails = await getJson(page, `/u/${encodeURIComponent(user.username)}/emails.json`, "with biber's own emails");
      expect(
        emails.email,
        mailbox
          ? "under the mailbox policy the Discourse email MUST stay the mailbox while the secondary address changes"
          : "expected the Discourse email to follow the Keycloak email",
      ).toBe(claimedEmail);
      const { user: details } = await getJson(page, `/u/${encodeURIComponent(user.username)}.json`, "with biber's own profile");
      expect(details.can_edit_name, "expected the IdP-managed name to be read-only in Discourse").toBe(false);
      expect(details.can_edit_email, "expected the IdP-managed email to be read-only in Discourse").toBe(false);
    } finally {
      await keycloakUpdateBiber(page.request, () => ({ ...previous, email: previous.email ?? "" })).catch((err) => {
        console.warn(`Restoring biber's Keycloak name and email failed: ${err}`);
      });
      await page.context().clearCookies().catch(() => {});
    }
  });
};
