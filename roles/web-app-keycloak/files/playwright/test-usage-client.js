const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { keycloakAdminToken, normalizeBaseUrl, requireDotenvValue } = require("./personas");

const issuerBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.ISSUER_BASE_URL, "ISSUER_BASE_URL"));
const realmName = requireDotenvValue(process.env.KEYCLOAK_REALM_NAME, "KEYCLOAK_REALM_NAME");
const superAdminUsername = requireDotenvValue(process.env.SUPER_ADMIN_USERNAME, "SUPER_ADMIN_USERNAME");
const superAdminPassword = requireDotenvValue(process.env.SUPER_ADMIN_PASSWORD, "SUPER_ADMIN_PASSWORD");
const usageEnabled = requireDotenvValue(process.env.KEYCLOAK_USAGE_CLIENT_ENABLED, "KEYCLOAK_USAGE_CLIENT_ENABLED") === "true";
const usageClientId = requireDotenvValue(process.env.KEYCLOAK_USAGE_CLIENT_ID, "KEYCLOAK_USAGE_CLIENT_ID");
const usageClientSecret = usageEnabled
  ? requireDotenvValue(process.env.KEYCLOAK_USAGE_CLIENT_SECRET, "KEYCLOAK_USAGE_CLIENT_SECRET")
  : "";

const realmPath = encodeURIComponent(realmName);
const adminApi = `${issuerBaseUrl}/admin/realms/${realmPath}`;
const tokenUrl = `${issuerBaseUrl}/realms/${realmPath}/protocol/openid-connect/token`;
const FIXTURE_USER = { username: "usagefixture", firstName: "Usage", lastName: "Fixture", email: "usagefixture@example.org" };
const PROBE_USER = { username: "usageprobe", firstName: "Usage", lastName: "Probe", email: "usageprobe@example.org" };
const REQUEST_MS = 30_000;

function bearer(token) {
  return { Authorization: `Bearer ${token}` };
}

async function requestUsageToken(request) {
  return request.post(tokenUrl, {
    form: { grant_type: "client_credentials", client_id: usageClientId, client_secret: usageClientSecret },
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    timeout: resolveTimeout(REQUEST_MS),
  });
}

async function usageToken(request) {
  const response = await requestUsageToken(request);
  expect(response.status(), "the usage client must receive a client-credentials token").toBe(200);
  return (await response.json()).access_token;
}

async function usersNamed(request, token, username) {
  const response = await request.get(`${adminApi}/users?username=${encodeURIComponent(username)}&exact=true`, {
    headers: bearer(token),
    timeout: resolveTimeout(REQUEST_MS),
  });
  expect(response.status(), `looking ${username} up must succeed`).toBe(200);
  return response.json();
}

async function deleteUsersNamed(request, token, username) {
  for (const user of await usersNamed(request, token, username)) {
    const response = await request.delete(`${adminApi}/users/${user.id}`, { headers: bearer(token), timeout: resolveTimeout(REQUEST_MS) });
    expect([204, 404], `removing ${username} must succeed`).toContain(response.status());
  }
}

async function withMasterToken(browser, body) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const masterToken = await keycloakAdminToken(context.request, issuerBaseUrl, superAdminUsername, superAdminPassword);
    await body(context.request, masterToken);
  } finally {
    await context.close();
  }
}

exports.register = function () {
  test.describe.serial("keycloak usage client", () => {
    test("usage client: reads users and changes nothing", async ({ browser }) => {
      test.skip(!usageEnabled, "KEYCLOAK_USAGE_CLIENT_ENABLED=false");
      let fixtureId;
      await withMasterToken(browser, async (request, masterToken) => {
        await deleteUsersNamed(request, masterToken, FIXTURE_USER.username);
        await deleteUsersNamed(request, masterToken, PROBE_USER.username);
        const created = await request.post(`${adminApi}/users`, {
          headers: { ...bearer(masterToken), "Content-Type": "application/json" },
          data: { ...FIXTURE_USER, enabled: true },
          timeout: resolveTimeout(REQUEST_MS),
        });
        expect(created.status(), "the super administrator must create the fixture user").toBe(201);
        fixtureId = created.headers()["location"].split("/").pop();
      });
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const { request } = context;
        const token = await usageToken(request);
        const headers = { ...bearer(token), "Content-Type": "application/json" };
        const listed = await request.get(`${adminApi}/users?first=0&max=100&briefRepresentation=false`, {
          headers,
          timeout: resolveTimeout(REQUEST_MS),
        });
        expect(listed.status(), "the usage client must list the users").toBe(200);
        expect(
          (await listed.json()).map((user) => user.username),
          "the usage client must see the fixture user",
        ).toContain(FIXTURE_USER.username);

        const created = await request.post(`${adminApi}/users`, {
          headers,
          data: { ...PROBE_USER, enabled: true },
          timeout: resolveTimeout(REQUEST_MS),
        });
        expect(created.status(), "the usage client must not create a user").toBe(403);
        const changed = await request.put(`${adminApi}/users/${fixtureId}`, {
          headers,
          data: { firstName: "Changed" },
          timeout: resolveTimeout(REQUEST_MS),
        });
        expect(changed.status(), "the usage client must not change a user").toBe(403);
        const removed = await request.delete(`${adminApi}/users/${fixtureId}`, { headers, timeout: resolveTimeout(REQUEST_MS) });
        expect(removed.status(), "the usage client must not delete a user").toBe(403);
        const realmUpdate = await request.put(adminApi, { headers, data: { realm: realmName }, timeout: resolveTimeout(REQUEST_MS) });
        expect(realmUpdate.status(), "the usage client must not change the realm").toBe(403);
      } finally {
        await context.close();
        await withMasterToken(browser, async (request, masterToken) => {
          await deleteUsersNamed(request, masterToken, PROBE_USER.username);
          await deleteUsersNamed(request, masterToken, FIXTURE_USER.username);
        });
      }
    });

    test("usage client: without its switch the realm holds no usage client", async ({ browser }) => {
      test.skip(usageEnabled, "KEYCLOAK_USAGE_CLIENT_ENABLED=true");
      await withMasterToken(browser, async (request, masterToken) => {
        const response = await request.get(`${adminApi}/clients?clientId=${encodeURIComponent(usageClientId)}`, {
          headers: bearer(masterToken),
          timeout: resolveTimeout(REQUEST_MS),
        });
        expect(response.status(), "looking the usage client up must succeed").toBe(200);
        expect(await response.json(), "the realm must hold no usage client").toEqual([]);
      });
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const response = await requestUsageToken(context.request);
        expect(response.status(), "a token request of a removed client must be refused").toBe(401);
      } finally {
        await context.close();
      }
    });
  });
};
