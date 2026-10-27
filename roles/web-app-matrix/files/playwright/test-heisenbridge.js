const { test, expect } = require("./onion-test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue } = require("./personas");

exports.register = function (shared) {
  test("heisenbridge: the bridge bot joins a DM and answers help", async ({ request }) => {
    const plugins = JSON.parse(decodeDotenvQuotedValue(process.env.MATRIX_PLUGINS_JSON || "") || "{}");
    test.skip(String(plugins.heisenbridge).toLowerCase() !== "true", "heisenbridge is not enabled");
    test.skip(decodeDotenvQuotedValue(process.env.MATRIX_FLAVOR) !== "ansible", "heisenbridge runs in the ansible flavor only");
    const { matrixBaseUrl, matrixServerName, adminUsername, adminPassword } = shared.env;
    const botId = `@heisenbridge:${matrixServerName}`;

    const { auth } = await shared.loginViaApi(request, adminUsername, adminPassword);
    const client = `${matrixBaseUrl}/_matrix/client/v3`;

    const createResponse = await request.post(`${client}/createRoom`, {
      headers: auth,
      data: { preset: "trusted_private_chat", is_direct: true, invite: [botId] },
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    });
    expect(createResponse.status(), `creating a DM with ${botId} must succeed: ${await createResponse.text()}`).toBe(200);
    const roomId = encodeURIComponent((await createResponse.json()).room_id);

    await expect
      .poll(async () => {
        const response = await request.get(`${client}/rooms/${roomId}/joined_members`, {
          headers: auth,
          failOnStatusCode: false,
          timeout: resolveTimeout(30_000),
        });
        return response.ok() ? Object.keys((await response.json()).joined || {}) : [];
      }, { timeout: resolveTimeout(60_000), message: `${botId} must accept the DM invite` })
      .toContain(botId);

    const sendResponse = await request.put(`${client}/rooms/${roomId}/send/m.room.message/playwright-${Date.now()}`, {
      headers: auth,
      data: { msgtype: "m.text", body: "help" },
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    });
    expect(sendResponse.status(), "sending help to the bot must succeed").toBe(200);
    const helpEventId = (await sendResponse.json()).event_id;

    await expect
      .poll(async () => {
        const response = await request.get(`${client}/rooms/${roomId}/messages?dir=b&limit=50`, {
          headers: auth,
          failOnStatusCode: false,
          timeout: resolveTimeout(30_000),
        });
        if (!response.ok()) return "";
        const events = (await response.json()).chunk || [];
        const newer = events.slice(0, events.findIndex((event) => event.event_id === helpEventId));
        return newer
          .filter((event) => event.sender === botId && event.type === "m.room.message")
          .map((event) => event.content?.body || "")
          .join("\n");
      }, { timeout: resolveTimeout(60_000), message: `${botId} must answer help` })
      .toMatch(/\S/);
  });
};
