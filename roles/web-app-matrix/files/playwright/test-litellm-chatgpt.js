// LiteLLM gateway scenario for the Matrix ChatGPT bridge (compose flavor).
//
// The bridge container reads CHATGPT_REVERSE_PROXY / CHATGPT_API_MODEL /
// OPENAI_API_KEY from MATRIX_CHATGPT_BRIDGE_* (roles/web-app-matrix/vars/main.yml),
// which resolve to the in-cluster svc-ai-litellm endpoint whenever
// services.litellm.enabled is true. Nothing on the Matrix HTTP surface exposes
// that container env, so the endpoint is asserted from the same Ansible values
// the compose template renders, and the round trip against @chatgptbot proves
// the bridge actually reaches an inference backend through it.
//
// Required env (rendered by templates/playwright.env.j2):
//   ADMIN_USERNAME, ADMIN_PASSWORD, MATRIX_BASE_URL, MATRIX_SERVER_NAME,
//   MATRIX_FLAVOR, MATRIX_PLUGINS_JSON, LITELLM_SERVICE_ENABLED,
//   MATRIX_CHATGPT_BRIDGE_ENDPOINT, MATRIX_CHATGPT_BRIDGE_MODEL.

const { test, expect } = require("@playwright/test");
const { decodeDotenvQuotedValue } = require("./personas");

const BOT_LOCALPART = "chatgptbot";
const PROMPT = "!chatgpt Reply with the single digit that is the result of 2+2.";
const BOT_FAILURE_PATTERN = /^\s*(something went wrong|there was an error|an error occurred|error:|failed to)/i;

const bridgeEndpoint = decodeDotenvQuotedValue(process.env.MATRIX_CHATGPT_BRIDGE_ENDPOINT || "");
const bridgeModel = decodeDotenvQuotedValue(process.env.MATRIX_CHATGPT_BRIDGE_MODEL || "");

function isTruthy(value) {
  if (value === true) return true;
  if (typeof value === "string") return value.toLowerCase() === "true";
  return false;
}

function authHeaders(accessToken) {
  return { Authorization: `Bearer ${accessToken}` };
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

/**
 * Args:
 *   request: Playwright APIRequestContext
 *   matrixBaseUrl: Synapse client-server base URL, no trailing slash
 *   username: localpart of the account registered by the deploy
 *   password: that account's password
 * Returns: the access token string, or null when every attempt was rejected.
 * Sets `diagnostic.last` to the final HTTP status/body for the caller's message.
 */
async function loginWithPassword(request, matrixBaseUrl, username, password, diagnostic) {
  const payload = {
    type: "m.login.password",
    identifier: { type: "m.id.user", user: username },
    password,
    initial_device_display_name: "infinito-litellm-gateway-probe",
  };
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const response = await request.post(`${matrixBaseUrl}/_matrix/client/v3/login`, {
      data: payload,
      failOnStatusCode: false,
    });
    const raw = await response.text().catch(() => "");
    if (response.ok()) {
      try {
        const token = JSON.parse(raw).access_token;
        if (token) return token;
      } catch {
        diagnostic.last = `HTTP 200 with unparseable body: ${raw.slice(0, 400)}`;
        return null;
      }
    }
    diagnostic.last = `HTTP ${response.status()}: ${raw.slice(0, 400)}`;
    if (response.status() !== 429) return null;
    let retryAfterMs = 5_000;
    try {
      retryAfterMs = Number(JSON.parse(raw).retry_after_ms) || 5_000;
    } catch {
      retryAfterMs = 5_000;
    }
    await sleep(Math.min(Math.max(retryAfterMs, 1_000), 30_000));
  }
  return null;
}

async function joinedMembers(request, matrixBaseUrl, roomId, accessToken) {
  const response = await request.get(
    `${matrixBaseUrl}/_matrix/client/v3/rooms/${encodeURIComponent(roomId)}/joined_members`,
    { headers: authHeaders(accessToken), failOnStatusCode: false },
  );
  if (!response.ok()) return [];
  const body = await response.json().catch(() => ({}));
  return Object.keys(body.joined || {});
}

async function botReplies(request, matrixBaseUrl, roomId, accessToken, botUserId) {
  const response = await request.get(
    `${matrixBaseUrl}/_matrix/client/v3/rooms/${encodeURIComponent(roomId)}/messages`,
    {
      headers: authHeaders(accessToken),
      params: { dir: "b", limit: "100" },
      failOnStatusCode: false,
    },
  );
  if (!response.ok()) return [];
  const body = await response.json().catch(() => ({}));
  return (body.chunk || [])
    .filter((event) => event && event.type === "m.room.message" && event.sender === botUserId)
    .map((event) => String((event.content || {}).body || "").trim());
}

exports.register = function (shared) {
  test("litellm: the matrix chatgpt bridge answers a prompt through the in-cluster gateway", async ({ request }) => {
    shared.skipUnlessServiceEnabled("litellm");
    test.skip(
      !(process.env.MATRIX_FLAVOR || "").toLowerCase().includes("compose"),
      "The matrix-chatgpt-bot bridge is only rendered by the compose flavor; the ansible flavor deploys matrix-docker-ansible-deploy, which owns its own bridge wiring.",
    );

    const { matrixBaseUrl, matrixServerName, adminUsername, adminPassword } = shared.env;
    const botUserId = `@${BOT_LOCALPART}:${matrixServerName}`;

    const plugins = JSON.parse(decodeDotenvQuotedValue(process.env.MATRIX_PLUGINS_JSON || "") || "{}");
    expect(
      isTruthy(plugins.chatgpt),
      `services.matrix.plugins.chatgpt must be on wherever svc-ai-litellm is deployed, otherwise the bridge container is never rendered and no Matrix surface reaches the gateway (MATRIX_PLUGINS_JSON: ${JSON.stringify(plugins)})`,
    ).toBe(true);

    expect(
      bridgeEndpoint,
      "MATRIX_CHATGPT_BRIDGE_ENDPOINT must be set; it is the value the compose template writes into the bridge's CHATGPT_REVERSE_PROXY",
    ).toBeTruthy();
    expect(
      bridgeEndpoint,
      "the bridge endpoint must be an absolute http(s) URL, otherwise the bridge cannot address any inference backend at all",
    ).toMatch(/^https?:\/\/.+/i);

    const endpointUrl = new URL(bridgeEndpoint);
    expect(
      endpointUrl.protocol,
      "the bridge endpoint must be plain http on the container network; https means the prompt leaves the cluster through the public ingress instead of reaching the gateway directly",
    ).toBe("http:");
    expect(
      endpointUrl.hostname.includes("."),
      `the bridge endpoint host must be an undotted container name (got "${endpointUrl.hostname}"); a dotted host is completed by the container dns-search suffix and resolves through the public ingress, which is the leak the requirement forbids`,
    ).toBe(false);
    expect(
      endpointUrl.pathname,
      "the bridge endpoint must be the gateway's OpenAI-compatible chat-completions path, so CHATGPT_REVERSE_PROXY is a drop-in replacement for the vendor URL",
    ).toBe("/v1/chat/completions");
    expect(
      bridgeEndpoint.toLowerCase(),
      `the bridge endpoint must not contain the public server name "${matrixServerName}"; a public hostname routes the prompt back out through the ingress rather than over the container network`,
    ).not.toContain(String(matrixServerName).toLowerCase());
    expect(
      bridgeModel,
      "MATRIX_CHATGPT_BRIDGE_MODEL must be set to the model the gateway serves; an empty CHATGPT_API_MODEL makes the bridge fall back to a vendor model name the gateway does not route",
    ).toBeTruthy();

    const loginDiagnostic = { last: "no attempt was made" };
    const accessToken = await loginWithPassword(
      request,
      matrixBaseUrl,
      adminUsername,
      adminPassword,
      loginDiagnostic,
    );
    expect(
      accessToken,
      `the administrator must be able to obtain a client-server access token by password (the deploy registers the account with register_new_matrix_user); last response: ${loginDiagnostic.last}`,
    ).toBeTruthy();

    let roomId = null;
    try {
      // Deliberately unencrypted: Element creates DMs with E2EE on, and an
      // encrypted timeline is opaque to this API-only client, so the bot's
      // answer would be unreadable. matrix-chatgpt-bot answers in plaintext
      // rooms too, which is what makes the completion observable here.
      const createResponse = await request.post(`${matrixBaseUrl}/_matrix/client/v3/createRoom`, {
        headers: authHeaders(accessToken),
        data: {
          preset: "private_chat",
          is_direct: true,
          invite: [botUserId],
          name: `litellm-gateway-probe-${Date.now()}`,
        },
        failOnStatusCode: false,
      });
      const createBody = await createResponse.text().catch(() => "");
      expect(
        createResponse.status(),
        `creating the probe room and inviting ${botUserId} must succeed; a 403/404 here means the deploy never registered the bridge's Matrix account: ${createBody.slice(0, 400)}`,
      ).toBe(200);
      roomId = JSON.parse(createBody).room_id;

      await expect
        .poll(async () => (await joinedMembers(request, matrixBaseUrl, roomId, accessToken)).includes(botUserId), {
          timeout: 180_000,
          intervals: [5_000],
          message: `${botUserId} must accept the invite (MATRIX_AUTOJOIN=true); if it never joins, the bridge container is not running or failed to authenticate against Synapse, so no prompt can reach the gateway`,
        })
        .toBe(true);

      const sendResponse = await request.put(
        `${matrixBaseUrl}/_matrix/client/v3/rooms/${encodeURIComponent(roomId)}/send/m.room.message/${encodeURIComponent(`litellm-probe-${Date.now()}`)}`,
        {
          headers: authHeaders(accessToken),
          data: { msgtype: "m.text", body: PROMPT },
          failOnStatusCode: false,
        },
      );
      expect(
        sendResponse.status(),
        `sending the probe prompt into the room must succeed: ${(await sendResponse.text().catch(() => "")).slice(0, 400)}`,
      ).toBe(200);

      let replies = [];
      await expect
        .poll(
          async () => {
            replies = await botReplies(request, matrixBaseUrl, roomId, accessToken, botUserId);
            return replies.length > 0;
          },
          {
            timeout: 300_000,
            intervals: [5_000],
            message: `${botUserId} must post an answer to the prompt; the bridge only posts once its chat-completions call returned, so silence means the request to ${bridgeEndpoint} never completed`,
          },
        )
        .toBe(true);

      const reply = replies[0];
      expect(
        reply.length,
        `the bridge's answer must be non-empty, proving the gateway returned a real completion rather than an empty choice (replies seen: ${JSON.stringify(replies)})`,
      ).toBeGreaterThan(0);
      expect(
        reply,
        `the bridge must answer with a completion, not with its own failure notice; this text is what matrix-chatgpt-bot posts when the call to ${bridgeEndpoint} raised: ${JSON.stringify(reply)}`,
      ).not.toMatch(BOT_FAILURE_PATTERN);
      expect(
        reply,
        `the bridge must answer the prompt rather than echo it back (got: ${JSON.stringify(reply)})`,
      ).not.toBe(PROMPT);
    } finally {
      if (roomId) {
        await request
          .post(`${matrixBaseUrl}/_matrix/client/v3/rooms/${encodeURIComponent(roomId)}/leave`, {
            headers: authHeaders(accessToken),
            data: {},
            failOnStatusCode: false,
          })
          .catch(() => {});
      }
      await request
        .post(`${matrixBaseUrl}/_matrix/client/v3/logout`, {
          headers: authHeaders(accessToken),
          data: {},
          failOnStatusCode: false,
        })
        .catch(() => {});
    }
  });
};
