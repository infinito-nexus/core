const { test, expect } = require("../onion-test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { decodeDotenvQuotedValue } = require("../personas");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

const HOOKSHOT_BOT_LOCALPART = "hookshot";

const FEED_PATH = "/explore/projects.atom";

async function loginWithPassword(request, matrixBaseUrl, username, password) {
  const response = await request.post(`${matrixBaseUrl}/_matrix/client/v3/login`, {
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
    data: {
      type: "m.login.password",
      identifier: { type: "m.id.user", user: username },
      password,
    },
  });
  expect(
    response.status(),
    `biber must obtain a client-server access token by password; the deploy provisions the account, ` +
      `so a 403 here means the password in the Playwright env no longer matches Synapse. ` +
      `HTTP ${response.status()}: ${(await response.text().catch(() => "")).slice(0, 300)}`,
  ).toBe(200);
  return (await response.json()).access_token;
}

async function botNotices(request, matrixBaseUrl, token, roomId, botUserId) {
  const response = await request.get(
    `${matrixBaseUrl}/_matrix/client/v3/rooms/${encodeURIComponent(roomId)}/messages?dir=b&limit=50`,
    { failOnStatusCode: false, timeout: resolveTimeout(30_000), headers: { Authorization: `Bearer ${token}` } },
  );
  if (response.status() !== 200) return [];
  const body = await response.json().catch(() => ({}));
  return (body.chunk || [])
    .filter((event) => event && event.type === "m.room.message" && event.sender === botUserId)
    .map((event) => String((event.content && event.content.body) || ""));
}

test("hookshot-feeds addon: biber subscribes a room to an RSS feed and hookshot confirms", async ({ request }) => {
  skipUnlessAddonEnabled("hookshot-feeds");
  skipUnlessServiceEnabled("gitlab");
  test.skip(
    !(process.env.MATRIX_FLAVOR || "").toLowerCase().includes("ansible"),
    "hookshot ships with the matrix-docker-ansible-deploy flavor only",
  );

  const plugins = JSON.parse(decodeDotenvQuotedValue(process.env.MATRIX_PLUGINS_JSON || "") || "{}");
  test.skip(
    !plugins.hookshot,
    `services.matrix.plugins.hookshot is off, so MDAD renders no hookshot bridge (MATRIX_PLUGINS_JSON: ${JSON.stringify(plugins)})`,
  );

  test.setTimeout(resolveTimeout(240_000));

  const matrixBaseUrl = (shared.env.matrixBaseUrl || "").replace(/\/$/, "");
  const matrixServerName = shared.env.matrixServerName;
  const gitlabBaseUrl = (decodeDotenvQuotedValue(process.env.GITLAB_BASE_URL) || "").replace(/\/$/, "");
  const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
  const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
  expect(matrixBaseUrl, "MATRIX_BASE_URL must be set").toBeTruthy();
  expect(gitlabBaseUrl, "GITLAB_BASE_URL must be set while the gitlab service is enabled").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();

  const botUserId = `@${HOOKSHOT_BOT_LOCALPART}:${matrixServerName}`;
  const feedUrl = `${gitlabBaseUrl}${FEED_PATH}`;
  const token = await loginWithPassword(request, matrixBaseUrl, biberUsername, biberPassword);
  const auth = { Authorization: `Bearer ${token}` };

  const createResponse = await request.post(`${matrixBaseUrl}/_matrix/client/v3/createRoom`, {
    failOnStatusCode: false,
    timeout: resolveTimeout(60_000),
    headers: auth,
    data: { preset: "private_chat", name: "hookshot feed probe", invite: [botUserId] },
  });
  expect(
    createResponse.status(),
    `creating the probe room must succeed: ${(await createResponse.text().catch(() => "")).slice(0, 300)}`,
  ).toBe(200);
  const roomId = (await createResponse.json()).room_id;

  await expect
    .poll(
      async () => {
        const members = await request.get(
          `${matrixBaseUrl}/_matrix/client/v3/rooms/${encodeURIComponent(roomId)}/joined_members`,
          { failOnStatusCode: false, timeout: resolveTimeout(30_000), headers: auth },
        );
        if (members.status() !== 200) return false;
        return Object.keys((await members.json()).joined || {}).includes(botUserId);
      },
      {
        timeout: resolveTimeout(120_000),
        message: `${botUserId} must accept the invite; if it never joins, the hookshot container is not running or failed to authenticate against Synapse, so no feed command can be processed`,
      },
    )
    .toBe(true);

  const sendResponse = await request.put(
    `${matrixBaseUrl}/_matrix/client/v3/rooms/${encodeURIComponent(roomId)}/send/m.room.message/${encodeURIComponent(`feed-probe-${process.pid}`)}`,
    {
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
      headers: auth,
      data: { msgtype: "m.text", body: `!hookshot feed ${feedUrl}` },
    },
  );
  expect(
    sendResponse.status(),
    `sending the feed command must succeed: ${(await sendResponse.text().catch(() => "")).slice(0, 300)}`,
  ).toBe(200);

  let replies = [];
  await expect
    .poll(
      async () => {
        replies = await botNotices(request, matrixBaseUrl, token, roomId, botUserId);
        return replies.length > 0;
      },
      {
        timeout: resolveTimeout(120_000),
        message: `${botUserId} must answer the feed command. Silence means the feeds module is off: MDAD renders it from matrix_bridge_hookshot_feeds_enabled, which follows the hookshot-feeds addon`,
      },
    )
    .toBe(true);

  expect(
    replies.some((body) => body.includes("Room configured to bridge")),
    `hookshot must confirm the subscription with "Room configured to bridge". It validates a feed by fetching ` +
      `it, so "Could not read feed from URL" means ${feedUrl} is not readable from inside the runner and the ` +
      `probe needs a different feed source, not that the addon is broken. Replies: ${JSON.stringify(replies)}`,
  ).toBe(true);
});
