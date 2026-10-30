const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");

const {
  decodeDotenvQuotedValue,
  gotoOnion,
  keycloakAdminAddUserToGroup,
  keycloakAdminSetUserAttributes,
  keycloakAdminToken,
  keycloakRemoveUserFromGroupViaRest,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  requireDotenvValue,
} = require("./personas");

const issuerBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.ISSUER_BASE_URL, "ISSUER_BASE_URL"));
const realmName = decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME);
const superAdminUsername = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME);
const superAdminPassword = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD);
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const groups = {
  userManager: decodeDotenvQuotedValue(process.env.CONSOLE_GROUP_USER_MANAGER),
  auditor: decodeDotenvQuotedValue(process.env.CONSOLE_GROUP_AUDITOR),
  impersonator: decodeDotenvQuotedValue(process.env.CONSOLE_GROUP_IMPERSONATOR),
};

const adminApi = `${issuerBaseUrl}/admin/realms/${encodeURIComponent(realmName)}`;

async function realmToken(request, username, password) {
  const response = await request.post(
    `${issuerBaseUrl}/realms/${encodeURIComponent(realmName)}/protocol/openid-connect/token`,
    {
      form: { client_id: "admin-cli", grant_type: "password", username, password },
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      timeout: resolveTimeout(30_000),
    },
  );
  expect(response.ok(), `${username} must obtain a realm token: ${response.status()}`).toBe(true);
  return (await response.json()).access_token;
}

async function userId(request, token, username) {
  const response = await request.get(`${adminApi}/users?username=${encodeURIComponent(username)}&exact=true`, {
    headers: { Authorization: `Bearer ${token}` },
    timeout: resolveTimeout(30_000),
  });
  expect(response.ok(), `user lookup for ${username} must succeed: ${response.status()}`).toBe(true);
  const match = (await response.json()).find((u) => u.username === username);
  expect(match, `Keycloak user ${username} must exist`).toBeTruthy();
  return match.id;
}

async function withBiberInGroup(browser, groupPath, body) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  let joined = false;
  try {
    joined = await keycloakAdminAddUserToGroup(
      context.request,
      issuerBaseUrl,
      realmName,
      groupPath,
      biberUsername,
      superAdminUsername,
      superAdminPassword,
    );
    await body(context.request);
  } finally {
    if (joined) {
      await keycloakRemoveUserFromGroupViaRest(
        context.request,
        issuerBaseUrl,
        realmName,
        superAdminUsername,
        superAdminPassword,
        groupPath,
        biberUsername,
      );
    }
    await context.close();
  }
}

exports.register = function () {
  test.describe.serial("keycloak admin console RBAC", () => {
    test("biber without a console role is refused by the admin API", async ({ browser }) => {
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const token = await realmToken(context.request, biberUsername, biberPassword);
        const users = await context.request.get(`${adminApi}/users?max=1`, {
          headers: { Authorization: `Bearer ${token}` },
          timeout: resolveTimeout(30_000),
        });
        expect(users.status(), "a user without a console role must not list users").toBe(403);
      } finally {
        await context.close();
      }
    });

    test("user-manager: biber lists and edits users of the application realm", async ({ browser }) => {
      await withBiberInGroup(browser, groups.userManager, async (request) => {
        const token = await realmToken(request, biberUsername, biberPassword);
        const headers = { Authorization: `Bearer ${token}` };
        const users = await request.get(`${adminApi}/users?max=5`, { headers, timeout: resolveTimeout(30_000) });
        expect(users.status(), "user-manager must list users").toBe(200);
        const events = await request.get(`${adminApi}/events?max=1`, { headers, timeout: resolveTimeout(30_000) });
        expect(events.status(), "user-manager must not read realm events").toBe(403);
      });
    });

    test("auditor: biber reads users and events but cannot create users", async ({ browser }) => {
      await withBiberInGroup(browser, groups.auditor, async (request) => {
        const token = await realmToken(request, biberUsername, biberPassword);
        const headers = { Authorization: `Bearer ${token}` };
        expect((await request.get(`${adminApi}/users?max=5`, { headers, timeout: resolveTimeout(30_000) })).status(), "auditor must list users").toBe(200);
        expect((await request.get(`${adminApi}/events?max=1`, { headers, timeout: resolveTimeout(30_000) })).status(), "auditor must read events").toBe(200);
        const create = await request.post(`${adminApi}/users`, {
          headers: { ...headers, "Content-Type": "application/json" },
          data: { username: "auditorprobe", enabled: false },
          timeout: resolveTimeout(30_000),
        });
        expect(create.status(), "auditor must not create users").toBe(403);
      });
    });

    test("impersonator: biber impersonates the realm administrator, without the role it is refused", async ({ browser }) => {
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const masterToken = await keycloakAdminToken(context.request, issuerBaseUrl, superAdminUsername, superAdminPassword);
        const targetId = await userId(context.request, masterToken, adminUsername);
        const plainToken = await realmToken(context.request, biberUsername, biberPassword);
        const refused = await context.request.post(`${adminApi}/users/${targetId}/impersonation`, {
          headers: { Authorization: `Bearer ${plainToken}` },
          timeout: resolveTimeout(30_000),
        });
        expect(refused.status(), "impersonation without the impersonator role must be refused").toBe(403);
      } finally {
        await context.close();
      }

      await withBiberInGroup(browser, groups.impersonator, async (request) => {
        const token = await realmToken(request, biberUsername, biberPassword);
        const targetId = await userId(request, token, adminUsername);
        const response = await request.post(`${adminApi}/users/${targetId}/impersonation`, {
          headers: { Authorization: `Bearer ${token}` },
          timeout: resolveTimeout(30_000),
        });
        expect(response.status(), "impersonator must be allowed to impersonate").toBe(200);
        const body = await response.json();
        expect(body.redirect, "impersonation must hand back the account console of the impersonated user").toContain(
          `/realms/${realmName}/account`,
        );
      });
    });

    test("administrator: biber's country, time zone and phonetic name round-trip through the directory", async ({ browser }) => {
      skipUnlessServiceEnabled("ldap");
      const wanted = { country: "DE", zoneinfo: "Europe/Berlin", namePhoneticGiven: "Hari" };
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      let previous = null;
      try {
        previous = await keycloakAdminSetUserAttributes(
          context.request,
          issuerBaseUrl,
          realmName,
          biberUsername,
          wanted,
          superAdminUsername,
          superAdminPassword,
        );
        const masterToken = await keycloakAdminToken(context.request, issuerBaseUrl, superAdminUsername, superAdminPassword);
        const id = await userId(context.request, masterToken, biberUsername);
        const response = await context.request.get(`${adminApi}/users/${id}`, {
          headers: { Authorization: `Bearer ${masterToken}` },
          timeout: resolveTimeout(30_000),
        });
        expect(response.ok(), `reading biber back must succeed: ${response.status()}`).toBe(true);
        const attributes = (await response.json()).attributes || {};
        for (const [name, value] of Object.entries(wanted)) {
          expect(attributes[name], `${name} must be stored in and read back from the directory`).toEqual([value]);
        }
      } finally {
        if (previous) {
          await keycloakAdminSetUserAttributes(
            context.request,
            issuerBaseUrl,
            realmName,
            biberUsername,
            previous,
            superAdminUsername,
            superAdminPassword,
          );
        }
        await context.close();
      }
    });

    test("profile: contact fields are editable by biber, organization fields are read-only", async ({ browser, page }) => {
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      let previous = null;
      try {
        previous = await keycloakAdminSetUserAttributes(
          context.request,
          issuerBaseUrl,
          realmName,
          biberUsername,
          { department: "Quality Assurance", phoneNumber: "+49 30 1234567" },
          superAdminUsername,
          superAdminPassword,
        );

        await gotoOnion(page, `${issuerBaseUrl}/realms/${realmName}/account/`);
        await performKeycloakLoginForm(page, biberUsername, biberPassword);
        await expect
          .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "biber must reach the account console" })
          .toContain("/account");

        const department = page.getByLabel(/^department$/i).first();
        await expect(department, "the department field must be shown").toBeVisible({ timeout: resolveTimeout(60_000) });
        await expect(department).toHaveValue("Quality Assurance");
        await expect(department, "organization fields must be read-only for the user").toBeDisabled();

        const phone = page.getByLabel(/^phone number$/i).first();
        await expect(phone).toHaveValue("+49 30 1234567");
        await expect(phone, "contact fields must be editable by the user").toBeEnabled();
      } finally {
        if (previous) {
          await keycloakAdminSetUserAttributes(
            context.request,
            issuerBaseUrl,
            realmName,
            biberUsername,
            previous,
            superAdminUsername,
            superAdminPassword,
          );
        }
        await context.close();
      }
    });
  });
};
