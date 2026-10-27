const { test, expect } = require("./onion-test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");

const ROOM_ALIAS_LOCALPART = "playwright-rtc";

exports.register = function (shared) {
  test("matrix-rtc: a member gets a LiveKit token from the JWT service and joins the SFU", async ({ page, request }) => {
    shared.skipUnlessServiceEnabled("element_call");
    test.skip(decodeDotenvQuotedValue(process.env.MATRIX_FLAVOR) !== "ansible", "the Matrix RTC stack runs in the ansible flavor only");
    const { matrixBaseUrl, matrixServerName, adminUsername, adminPassword } = shared.env;

    const session = await shared.loginViaApi(request, adminUsername, adminPassword);
    const { auth } = session;

    const transportsResponse = await request.get(
      `${matrixBaseUrl}/_matrix/client/unstable/org.matrix.msc4143/rtc/transports`,
      { headers: auth, failOnStatusCode: false, timeout: resolveTimeout(30_000) },
    );
    expect(transportsResponse.status(), "Synapse must serve the MSC4143 RTC transports API").toBe(200);
    const transports = (await transportsResponse.json()).rtc_transports || [];
    const livekit = transports.find((transport) => transport.type === "livekit");
    expect(livekit, `Synapse must advertise a livekit transport, got ${JSON.stringify(transports)}`).toBeTruthy();
    const jwtServiceUrl = livekit.livekit_service_url.replace(/\/+$/, "");
    expect(jwtServiceUrl).toBe(`${matrixBaseUrl}${decodeDotenvQuotedValue(process.env.MATRIX_LIVEKIT_JWT_PATH)}`);

    const openIdResponse = await request.post(
      `${matrixBaseUrl}/_matrix/client/v3/user/${encodeURIComponent(session.user_id)}/openid/request_token`,
      { headers: auth, data: {}, failOnStatusCode: false, timeout: resolveTimeout(30_000) },
    );
    expect(openIdResponse.status(), "Synapse must issue an OpenID token").toBe(200);
    const openIdToken = await openIdResponse.json();

    const roomId = `!${ROOM_ALIAS_LOCALPART}-${Date.now()}:${matrixServerName}`;
    const sfuResponse = await request.post(`${jwtServiceUrl}/sfu/get`, {
      data: { room: roomId, openid_token: openIdToken, device_id: session.device_id },
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    });
    expect(sfuResponse.status(), `the JWT service must exchange the OpenID token: ${await sfuResponse.text()}`).toBe(200);
    const sfu = await sfuResponse.json();
    expect(sfu.url, "the JWT service must name the LiveKit websocket").toBe(
      `${matrixBaseUrl.replace(/^http/, "ws")}${decodeDotenvQuotedValue(process.env.MATRIX_LIVEKIT_PATH)}`,
    );
    expect(sfu.jwt, "the JWT service must return a LiveKit token").toBeTruthy();

    await gotoOnion(page, `${matrixBaseUrl}/_matrix/client/versions`, { waitUntil: "domcontentloaded" });
    const joined = await page.evaluate(
      ({ url, token, timeoutMs }) =>
        new Promise((resolve) => {
          const socket = new WebSocket(`${url}/rtc?access_token=${encodeURIComponent(token)}&protocol=15&auto_subscribe=1`);
          socket.binaryType = "arraybuffer";
          const timer = setTimeout(() => resolve({ ok: false, reason: "timeout" }), timeoutMs);
          socket.onmessage = (event) => {
            clearTimeout(timer);
            socket.close();
            resolve({ ok: event.data.byteLength > 0, reason: `first frame ${event.data.byteLength} bytes` });
          };
          socket.onerror = () => {
            clearTimeout(timer);
            resolve({ ok: false, reason: "websocket error" });
          };
          socket.onclose = (event) => {
            clearTimeout(timer);
            resolve({ ok: false, reason: `closed ${event.code} ${event.reason}` });
          };
        }),
      { url: sfu.url, token: sfu.jwt, timeoutMs: resolveTimeout(30_000) },
    );
    expect(joined.ok, `LiveKit must answer the signal connection with a join response (${joined.reason})`).toBe(true);
  });
};
