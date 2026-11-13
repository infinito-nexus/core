const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { keycloakAdminToken, normalizeBaseUrl, requireDotenvValue } = require("./personas");

const issuerBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.ISSUER_BASE_URL, "ISSUER_BASE_URL"));
const realmName = requireDotenvValue(process.env.KEYCLOAK_REALM_NAME, "KEYCLOAK_REALM_NAME");
const superAdminUsername = requireDotenvValue(process.env.SUPER_ADMIN_USERNAME, "SUPER_ADMIN_USERNAME");
const superAdminPassword = requireDotenvValue(process.env.SUPER_ADMIN_PASSWORD, "SUPER_ADMIN_PASSWORD");
const directoryEnabled =
  requireDotenvValue(process.env.KEYCLOAK_DIRECTORY_CLIENT_ENABLED, "KEYCLOAK_DIRECTORY_CLIENT_ENABLED") === "true";
const directoryClientId = requireDotenvValue(process.env.KEYCLOAK_DIRECTORY_CLIENT_ID, "KEYCLOAK_DIRECTORY_CLIENT_ID");
const directoryClientSecret = directoryEnabled
  ? requireDotenvValue(process.env.KEYCLOAK_DIRECTORY_CLIENT_SECRET, "KEYCLOAK_DIRECTORY_CLIENT_SECRET")
  : "";

const realmPath = encodeURIComponent(realmName);
const adminApi = `${issuerBaseUrl}/admin/realms/${realmPath}`;
const tokenUrl = `${issuerBaseUrl}/realms/${realmPath}/protocol/openid-connect/token`;
const PROBE_USER = { username: "dirprobe", firstName: "Directory", lastName: "Probe", email: "dirprobe@example.org" };
const FIXTURE_USER = { username: "dirfixture", firstName: "Directory", lastName: "Fixture", email: "dirfixture@example.org" };
const PROBE_ROLE = "directory-probe";
const PROBE_CLIENT_ID = "directory-probe-client";
const ENABLED_ONLY = "KEYCLOAK_DIRECTORY_CLIENT_ENABLED=false";

function bearer(token) {
  return { Authorization: `Bearer ${token}` };
}

async function requestDirectoryToken(request) {
  return request.post(tokenUrl, {
    form: { grant_type: "client_credentials", client_id: directoryClientId, client_secret: directoryClientSecret },
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    timeout: resolveTimeout(30_000),
  });
}

async function directoryToken(request) {
  const response = await requestDirectoryToken(request);
  expect(response.status(), "the directory client must receive a client-credentials token").toBe(200);
  return (await response.json()).access_token;
}

async function readJson(request, token, url, message) {
  const response = await request.get(url, { headers: bearer(token), timeout: resolveTimeout(30_000) });
  expect(response.status(), `${message}: ${url}`).toBe(200);
  return response.json();
}

async function usersNamed(request, token, username) {
  return readJson(
    request,
    token,
    `${adminApi}/users?username=${encodeURIComponent(username)}&exact=true`,
    `looking ${username} up must succeed`,
  );
}

async function deleteUsersNamed(request, token, username) {
  for (const user of await usersNamed(request, token, username)) {
    const response = await request.delete(`${adminApi}/users/${user.id}`, {
      headers: bearer(token),
      timeout: resolveTimeout(30_000),
    });
    expect([204, 404], `removing ${username} must succeed`).toContain(response.status());
  }
}

async function ensureProbeRole(request, masterToken) {
  const response = await request.post(`${adminApi}/roles`, {
    headers: { ...bearer(masterToken), "Content-Type": "application/json" },
    data: { name: PROBE_ROLE, description: "Realm role the directory client spec assigns to its probe user." },
    timeout: resolveTimeout(30_000),
  });
  expect([201, 409], `the super administrator must create the realm role ${PROBE_ROLE}`).toContain(response.status());
}

async function createUser(request, token, user) {
  return request.post(`${adminApi}/users`, {
    headers: { ...bearer(token), "Content-Type": "application/json" },
    data: { ...user, enabled: true },
    timeout: resolveTimeout(30_000),
  });
}

async function ensureFixtureUser(request, masterToken) {
  await deleteUsersNamed(request, masterToken, FIXTURE_USER.username);
  const created = await createUser(request, masterToken, FIXTURE_USER);
  expect(created.status(), "the super administrator must create the fixture user to search for").toBe(201);
}

async function removeProbeRole(request, masterToken) {
  const response = await request.delete(`${adminApi}/roles/${encodeURIComponent(PROBE_ROLE)}`, {
    headers: bearer(masterToken),
    timeout: resolveTimeout(30_000),
  });
  expect([204, 404], `removing the realm role ${PROBE_ROLE} must succeed`).toContain(response.status());
}

async function removeProbeClients(request, masterToken) {
  const clients = await readJson(
    request,
    masterToken,
    `${adminApi}/clients?clientId=${encodeURIComponent(PROBE_CLIENT_ID)}`,
    "looking the probe client up must succeed",
  );
  for (const client of clients) {
    const response = await request.delete(`${adminApi}/clients/${client.id}`, {
      headers: bearer(masterToken),
      timeout: resolveTimeout(30_000),
    });
    expect([204, 404], "removing the probe client must succeed").toContain(response.status());
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
  test.describe.serial("keycloak directory client", () => {
    test("directory client: lists, finds, creates, assigns a role to and deletes a user of the realm", async ({ browser }) => {
      test.skip(!directoryEnabled, ENABLED_ONLY);
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        await withMasterToken(browser, async (request, masterToken) => {
          await ensureProbeRole(request, masterToken);
          await ensureFixtureUser(request, masterToken);
        });
        const { request } = context;
        const token = await directoryToken(request);
        await deleteUsersNamed(request, token, PROBE_USER.username);

        const listed = await readJson(request, token, `${adminApi}/users?first=0&max=100`, "the directory client must list the users");
        expect(listed.length, "the realm must hold at least one user").toBeGreaterThan(0);
        const byUsername = await usersNamed(request, token, FIXTURE_USER.username);
        expect(byUsername.map((user) => user.username), "the username search must find the fixture user").toEqual([
          FIXTURE_USER.username,
        ]);
        const byEmail = await readJson(
          request,
          token,
          `${adminApi}/users?email=${encodeURIComponent(FIXTURE_USER.email)}&exact=true`,
          "the directory client must search users by email",
        );
        expect(byEmail.map((user) => user.username), "the email search must find the fixture user").toEqual([
          FIXTURE_USER.username,
        ]);

        const created = await createUser(request, token, PROBE_USER);
        expect(created.status(), "the directory client must create the probe user").toBe(201);
        const probeId = created.headers()["location"].split("/").pop();
        expect(probeId, "the created user must carry an id").toBeTruthy();

        const available = await readJson(
          request,
          token,
          `${adminApi}/users/${probeId}/role-mappings/realm/available`,
          "the directory client must list the realm roles it may map",
        );
        const role = available.find((candidate) => candidate.name === PROBE_ROLE);
        expect(role, `the available realm roles must offer ${PROBE_ROLE}`).toBeTruthy();
        const mapped = await request.post(`${adminApi}/users/${probeId}/role-mappings/realm`, {
          headers: { ...bearer(token), "Content-Type": "application/json" },
          data: [role],
          timeout: resolveTimeout(30_000),
        });
        expect(mapped.status(), `the directory client must assign ${PROBE_ROLE}`).toBe(204);
        const held = await readJson(
          request,
          token,
          `${adminApi}/users/${probeId}/role-mappings/realm`,
          "the directory client must read the probe user's realm roles",
        );
        expect(held.map((candidate) => candidate.name), "the probe user must hold the assigned role").toContain(PROBE_ROLE);

        const removed = await request.delete(`${adminApi}/users/${probeId}`, {
          headers: bearer(token),
          timeout: resolveTimeout(30_000),
        });
        expect(removed.status(), "the directory client must delete the probe user").toBe(204);
        expect(await usersNamed(request, token, PROBE_USER.username), "the probe user must be gone").toEqual([]);
      } finally {
        await context.close();
        await withMasterToken(browser, async (request, masterToken) => {
          await deleteUsersNamed(request, masterToken, PROBE_USER.username);
          await deleteUsersNamed(request, masterToken, FIXTURE_USER.username);
          await removeProbeRole(request, masterToken);
        });
      }
    });

    test("directory client: may neither change the realm, nor read its roles, nor reach another realm", async ({ browser }) => {
      test.skip(!directoryEnabled, ENABLED_ONLY);
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const { request } = context;
        const headers = { ...bearer(await directoryToken(request)), "Content-Type": "application/json" };
        const realmUpdate = await request.put(adminApi, {
          headers,
          data: { realm: realmName },
          timeout: resolveTimeout(30_000),
        });
        expect(realmUpdate.status(), "the directory client must not change the realm").toBe(403);
        const clientCreate = await request.post(`${adminApi}/clients`, {
          headers,
          data: { clientId: PROBE_CLIENT_ID, enabled: false },
          timeout: resolveTimeout(30_000),
        });
        expect(clientCreate.status(), "the directory client must not create clients").toBe(403);
        const roleRead = await request.get(`${adminApi}/roles/offline_access`, { headers, timeout: resolveTimeout(30_000) });
        expect(roleRead.status(), "the directory client must not read the realm's role configuration").toBe(403);
        const masterUsers = await request.get(`${issuerBaseUrl}/admin/realms/master/users?max=1`, {
          headers,
          timeout: resolveTimeout(30_000),
        });
        expect([401, 403], "the directory client must not reach the master realm").toContain(masterUsers.status());
      } finally {
        await context.close();
        await withMasterToken(browser, (request, masterToken) => removeProbeClients(request, masterToken));
      }
    });

    test("directory client: without its switch the realm holds no directory client", async ({ browser }) => {
      test.skip(directoryEnabled, "KEYCLOAK_DIRECTORY_CLIENT_ENABLED=true");
      await withMasterToken(browser, async (request, masterToken) => {
        const clients = await readJson(
          request,
          masterToken,
          `${adminApi}/clients?clientId=${encodeURIComponent(directoryClientId)}`,
          "looking the directory client up must succeed",
        );
        expect(clients, "the realm must hold no directory client").toEqual([]);
      });
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const response = await requestDirectoryToken(context.request);
        expect(response.status(), "a token request of a removed client must be refused").toBe(401);
        expect((await response.json()).error, "the refusal must name the client").toBe("invalid_client");
      } finally {
        await context.close();
      }
    });
  });
};
