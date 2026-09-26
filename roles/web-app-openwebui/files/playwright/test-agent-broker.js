const { test, expect, request } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue } = require("./personas");

const kcBaseUrl = decodeDotenvQuotedValue(process.env.KEYCLOAK_BASE_URL || "").replace(/\/$/, "");
const kcRealm = decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM || "");
const kcAdminUser = decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_USERNAME || "");
const kcAdminPw = decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_PASSWORD || "");
function agentGroups() {
  const raw = decodeDotenvQuotedValue(process.env.AGENT_GROUP_PATHS || "");
  expect(raw, "AGENT_GROUP_PATHS must be rendered while the broker is enabled").toBeTruthy();
  return JSON.parse(raw);
}

async function keycloakAdmin() {
  const api = await request.newContext({ ignoreHTTPSErrors: true });
  const tokenResp = await api.post(`${kcBaseUrl}/realms/master/protocol/openid-connect/token`, {
    form: { client_id: "admin-cli", username: kcAdminUser, password: kcAdminPw, grant_type: "password" },
  });
  expect(tokenResp.ok(), `Keycloak admin token (HTTP ${tokenResp.status()})`).toBeTruthy();
  const headers = { Authorization: `Bearer ${(await tokenResp.json()).access_token}` };
  return { api, headers };
}

/**
 * Put one user into, or take it out of, the named agent groups.
 *
 * Args:
 *   username: the Keycloak username to change.
 *   membership: group path -> whether the user must end up a member.
 */
async function applyAgentGroups(username, membership) {
  const { api, headers } = await keycloakAdmin();
  try {
    const users = await (
      await api.get(`${kcBaseUrl}/admin/realms/${kcRealm}/users?username=${encodeURIComponent(username)}&exact=true`, { headers })
    ).json();
    expect(users, `Keycloak user ${username} must exist`).toHaveLength(1);
    for (const [path, member] of Object.entries(membership)) {
      const groupResp = await api.get(`${kcBaseUrl}/admin/realms/${kcRealm}/group-by-path${path}`, { headers });
      expect(groupResp.ok(), `Keycloak group ${path} must exist (HTTP ${groupResp.status()})`).toBeTruthy();
      const url = `${kcBaseUrl}/admin/realms/${kcRealm}/users/${users[0].id}/groups/${(await groupResp.json()).id}`;
      const resp = member ? await api.put(url, { headers }) : await api.delete(url, { headers });
      expect([200, 204, 404]).toContain(resp.status());
    }
  } finally {
    await api.dispose();
  }
}

async function setAgentGroups(username, member) {
  await applyAgentGroups(
    username,
    Object.fromEntries(Object.values(agentGroups()).map((path) => [path, member])),
  );
}

/**
 * Leave the user in exactly one platform's agent group.
 *
 * Args:
 *   username: the Keycloak username to change.
 *   granted: the platform whose group the user keeps; every other is removed.
 */
async function grantOnlyAgentGroup(username, granted) {
  const groups = agentGroups();
  await applyAgentGroups(
    username,
    Object.fromEntries(Object.entries(groups).map(([platform, path]) => [path, platform === granted])),
  );
}

async function openwebuiSession(shared, page) {
  await shared.signInViaDashboardOidc(page, shared.env.biberUsername, shared.env.biberPassword, "biber");
  const token = await page.evaluate(() => window.localStorage.getItem("token"));
  expect(token, "OpenWebUI must store a session token for biber").toBeTruthy();
  return {
    base: shared.env.openwebuiBaseUrl.replace(/\/+$/, ""),
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  };
}

/**
 * Run work inside a fresh Open WebUI administrator session.
 *
 * Args:
 *   page: any page; its browser opens the administrator context.
 *   shared: the role's shared spec helpers.
 *   work: async (adminPage, admin) => result, where admin holds base and headers.
 */
async function asAdministrator(page, shared, work) {
  const context = await page.context().browser().newContext({ ignoreHTTPSErrors: true });
  try {
    const adminPage = await context.newPage();
    await shared.signInViaDashboardOidc(adminPage, shared.env.adminUsername, shared.env.adminPassword, "administrator");
    const token = await adminPage.evaluate(() => window.localStorage.getItem("token"));
    expect(token, "OpenWebUI must store a session token for the administrator").toBeTruthy();
    return await work(adminPage, {
      base: shared.env.openwebuiBaseUrl.replace(/\/+$/, ""),
      headers: { Authorization: `Bearer ${token}` },
    });
  } finally {
    await context.close();
  }
}

/**
 * Take one user out of every Open WebUI agent group.
 *
 * Args:
 *   adminPage: a page holding an administrator session.
 *   admin: the administrator's base URL and headers.
 *   userId: the Open WebUI user id to remove.
 *
 * Open WebUI's OIDC sync drops a stale group only while the groups claim is
 * non-empty; biber loses its last group here, so the revocation in Keycloak
 * never reaches Open WebUI on its own.
 */
async function dropAgentMemberships(adminPage, admin, userId) {
  const listed = await adminPage.request.get(`${admin.base}/api/v1/groups/`, { headers: admin.headers });
  expect(listed.ok(), `the administrator must list the groups (HTTP ${listed.status()})`).toBeTruthy();
  const paths = Object.values(agentGroups());
  for (const group of (await listed.json()).filter((g) => paths.includes(g?.name))) {
    const removed = await adminPage.request.post(`${admin.base}/api/v1/groups/id/${group.id}/users/remove`, {
      headers: admin.headers,
      data: { user_ids: [userId] },
    });
    expect(removed.ok(), `the administrator must remove ${userId} from ${group.name} (HTTP ${removed.status()})`).toBeTruthy();
  }
}

/**
 * Run work inside a browser context that has just signed biber in.
 *
 * A membership change only reaches Open WebUI through a fresh OIDC sign-in, so
 * every step of the per-group walk needs its own context rather than a reused
 * token that still carries the previous groups claim.
 *
 * Args:
 *   page: any page; its browser opens the new context.
 *   shared: the role's shared spec helpers.
 *   work: async (biberPage, session) => result.
 */
async function asBiber(page, shared, work) {
  const context = await page.context().browser().newContext({ ignoreHTTPSErrors: true });
  try {
    const biberPage = await context.newPage();
    const session = await openwebuiSession(shared, biberPage);
    return await work(biberPage, session);
  } finally {
    await context.close();
  }
}

async function sessionUserId(page, session) {
  const me = await page.request.get(`${session.base}/api/v1/auths/`, { headers: session.headers });
  expect(me.ok(), `OpenWebUI must report the signed-in user's id (HTTP ${me.status()})`).toBeTruthy();
  return (await me.json()).id;
}

async function listedModels(page, session, path) {
  const resp = await page.request.get(`${session.base}${path}`, { headers: session.headers });
  expect(resp.ok(), `OpenWebUI ${path} (HTTP ${resp.status()})`).toBeTruthy();
  const body = await resp.json();
  return (Array.isArray(body?.data) ? body.data : []).map((m) => String(m?.id ?? ""));
}

exports.register = function (shared) {
  test("biber: without agent-user no agent model is listed or answers", async ({ page }) => {
    skipUnlessServiceEnabled("agent-broker");
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(180_000));

    await setAgentGroups(shared.env.biberUsername, false);
    const session = await openwebuiSession(shared, page);
    const biberId = await sessionUserId(page, session);
    const servedModels = await asAdministrator(page, shared, async (adminPage, admin) => {
      await dropAgentMemberships(adminPage, admin, biberId);
      return listedModels(adminPage, admin, "/openai/models");
    });
    const models = await listedModels(page, session, "/api/models?refresh=true");
    const gatewayModels = servedModels.filter((id) => !(id in agentGroups()));
    if (isServiceEnabled("litellm")) {
      expect(gatewayModels.length, "the connections must serve the gateway models").toBeGreaterThan(0);
    }
    for (const model of gatewayModels) {
      expect(models, `the gateway model ${model} must be granted to every user`).toContain(model);
    }
    for (const platform of Object.keys(agentGroups())) {
      expect(models, `${platform} is granted to its agent-user group only`).not.toContain(platform);
      const chat = await page.request.post(`${session.base}/api/chat/completions`, {
        headers: session.headers,
        data: { model: platform, messages: [{ role: "user", content: "ping" }], stream: false },
        failOnStatusCode: false,
      });
      expect(chat.ok(), `a completion on ${platform} must be refused for biber (HTTP ${chat.status()})`).toBeFalsy();
    }
  });

  test("biber: with agent-user each platform starts a personal agent that answers", async ({ page }) => {
    skipUnlessServiceEnabled("agent-broker");
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(3_600_000));

    await setAgentGroups(shared.env.biberUsername, true);
    try {
      const session = await openwebuiSession(shared, page);
      const models = await listedModels(page, session, "/api/models?refresh=true");
      for (const platform of Object.keys(agentGroups())) {
        expect(models, `${platform} must be listed once biber holds its agent-user group`).toContain(platform);
        const chat = await page.request.post(`${session.base}/api/chat/completions`, {
          headers: session.headers,
          data: {
            model: platform,
            messages: [{ role: "user", content: "Reply with exactly the word: pong" }],
            stream: false,
          },
          timeout: resolveTimeout(1_800_000),
        });
        expect(chat.ok(), `the ${platform} agent must answer through the broker (HTTP ${chat.status()})`).toBeTruthy();
        const content = ((await chat.json())?.choices?.[0]?.message?.content ?? "").trim();
        expect(content, `the ${platform} agent must return an answer through the broker`).not.toBe("");
      }
    } finally {
      await setAgentGroups(shared.env.biberUsername, false);
    }
  });

  test("biber: each agent-user group grants exactly its own platform, and revoking it takes that platform away", async ({ page }) => {
    skipUnlessServiceEnabled("agent-broker");
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(3_600_000));

    const platforms = Object.keys(agentGroups());
    expect(platforms.length, "the broker must offer at least one platform to walk").toBeGreaterThan(0);

    try {
      for (const granted of platforms) {
        await grantOnlyAgentGroup(shared.env.biberUsername, granted);
        await asBiber(page, shared, async (biberPage, session) => {
          const models = await listedModels(biberPage, session, "/api/models?refresh=true");
          expect(models, `${granted} must be listed while biber holds only its group`).toContain(granted);
          const answered = await biberPage.request.post(`${session.base}/api/chat/completions`, {
            headers: session.headers,
            data: { model: granted, messages: [{ role: "user", content: "ping" }], stream: false },
            timeout: resolveTimeout(1_800_000),
          });
          expect(answered.ok(), `the ${granted} agent must answer while its group is held (HTTP ${answered.status()})`).toBeTruthy();

          for (const withheld of platforms.filter((platform) => platform !== granted)) {
            expect(models, `${withheld} must stay hidden while biber holds only the ${granted} group`).not.toContain(withheld);
            const refused = await biberPage.request.post(`${session.base}/api/chat/completions`, {
              headers: session.headers,
              data: { model: withheld, messages: [{ role: "user", content: "ping" }], stream: false },
              failOnStatusCode: false,
            });
            expect(refused.ok(), `${withheld} must stay refused while biber holds only the ${granted} group (HTTP ${refused.status()})`).toBeFalsy();
          }
        });
      }
    } finally {
      await setAgentGroups(shared.env.biberUsername, false);
    }

    const lastGranted = platforms[platforms.length - 1];
    await asBiber(page, shared, async (biberPage, session) => {
      const biberId = await sessionUserId(biberPage, session);
      await asAdministrator(biberPage, shared, (adminPage, admin) => dropAgentMemberships(adminPage, admin, biberId));
    });
    await asBiber(page, shared, async (biberPage, session) => {
      const models = await listedModels(biberPage, session, "/api/models?refresh=true");
      expect(models, `${lastGranted} must disappear once its group is revoked`).not.toContain(lastGranted);
      const refused = await biberPage.request.post(`${session.base}/api/chat/completions`, {
        headers: session.headers,
        data: { model: lastGranted, messages: [{ role: "user", content: "ping" }], stream: false },
        failOnStatusCode: false,
      });
      expect(refused.ok(), `${lastGranted} must be refused once its group is revoked (HTTP ${refused.status()})`).toBeFalsy();
    });
  });
};
